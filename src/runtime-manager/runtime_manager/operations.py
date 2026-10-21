"""Platform-owned operation executor. Local locks supplement persistent fencing."""

from __future__ import annotations

import logging
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Event, Lock, Thread

from runtime_manager.bundle_launch import BundleLauncher
from runtime_manager.bundle_preparer import BundlePreparer
from runtime_manager.container_runner import OP_LABEL, PHASE_LABEL, ContainerRunner, ExecutionError
from runtime_manager.docker_backend import get_docker_backend
from runtime_manager.platform_appdb import PlatformAppDb
from runtime_manager.platform_client import PlatformClient

logger = logging.getLogger(__name__)
TERMINAL = {"completed", "failed", "cancelled", "timed_out"}


class OperationExecutor:
    def __init__(self, config, platform=None, docker=None, *, clock=time):
        self.config = config
        self.platform = platform or PlatformClient(config)
        self.docker = docker or get_docker_backend()
        self.clock = clock
        self._closing = Event()
        self._guard = Lock()
        self._apps = {}
        self._running = {}
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="runtime-v2")
        self._observers = ThreadPoolExecutor(max_workers=2, thread_name_prefix="runtime-observe")
        self._observing = {}

    def submit(self, operation_id):
        operation = self.platform.operation(operation_id)
        if operation["status"] in TERMINAL:
            return operation
        with self._guard:
            previous = self._running.get(operation_id)
            if previous is None or previous.done():
                self._running[operation_id] = self._pool.submit(self.execute, operation_id)
        return operation

    def checkpoint(self, operation):
        if self._closing.is_set():
            raise ExecutionError("manager_stopping")
        current = self.platform.operation(operation["operation_id"])
        if any(current.get(key) != operation.get(key) for key in ("node_id", "generation", "owner_epoch", "app_id")):
            raise ExecutionError("execution_fence_mismatch")
        if (
            current["status"] in TERMINAL
            or current.get("cancel_requested")
            or current["payload"].get("cancel_requested")
        ):
            raise ExecutionError("operation_cancelled")
        deadline = datetime.fromisoformat(current["deadline"].replace("Z", "+00:00"))
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)
        if datetime.now(UTC) >= deadline:
            raise ExecutionError("operation_timeout")
        return current

    def report(self, operation, phase, *, exec_ref="", detail=None):
        # Retries query the committed sequence, never guess whether a fact was accepted.
        current = self.platform.operation(operation["operation_id"])
        return self.platform.fact(
            operation, int(current.get("fact_sequence", 0)) + 1, phase, exec_ref=exec_ref, detail=detail
        )

    def executions(self, app_id=None, operation_id=None):
        labels = ["bisheng.managed=v2", f"bisheng.runtime.node={self.config.node_id}"]
        if app_id:
            labels.append(f"bisheng.app.id={app_id}")
        if operation_id:
            labels.append(f"{OP_LABEL}={operation_id}")
        return self.docker.list_containers(all_states=True, filters={"label": labels})

    def stop_instances(self, operation, *, include_current=True):
        items = self.executions(app_id=operation["app_id"])
        scope = self.platform.application(operation["app_id"])
        if scope.get("exec_ref"):
            try:
                legacy = self.docker.inspect_container(scope["exec_ref"])
                labels = legacy.get("Config", {}).get("Labels", {})
                if labels.get("bisheng.managed") == "true":
                    if labels.get("bisheng.app.id") != operation["app_id"]:
                        raise ExecutionError("legacy_execution_scope_mismatch")
                    items.append(
                        {"Id": scope["exec_ref"], "Labels": {PHASE_LABEL: "serve", OP_LABEL: scope["operation_id"]}}
                    )
            except Exception as exc:
                if getattr(exc, "status_code", None) != 404:
                    raise
        for item in items:
            labels = item.get("Labels", {})
            if labels.get(PHASE_LABEL) != "serve":
                continue
            if not include_current and labels.get(OP_LABEL) == operation["operation_id"]:
                continue
            self.checkpoint(operation)
            ident = item["Id"]
            if self.docker.inspect_container(ident).get("State", {}).get("Running"):
                self.docker.stop_container(ident, timeout=self.config.stop_timeout_seconds)
            if self.docker.inspect_container(ident).get("State", {}).get("Running"):
                raise ExecutionError("writer_stop_unconfirmed")

    def _launch(self, operation, runner, *, preview=False):
        body = operation["payload"]
        if self.config.egress_enabled:
            from runtime_manager.egress import egress_env

            credentials = self.platform.egress(operation["operation_id"], "runtime")
            body["runtime_env"] = {**body.get("runtime_env", {}), **egress_env(self.config, **credentials)}
        delivery = body["resolved_delivery"]
        paths = (
            BundlePreparer(self.config, self.platform, runner=runner).restore(operation, delivery)
            if delivery["mode"] == "bundle"
            else {}
        )
        if preview:
            from runtime_manager.appdb import AppDbSchemaService

            isolated = self.config.with_overrides(
                data_root=self.config.data_root / "previews" / operation["operation_id"]
            )
            AppDbSchemaService(isolated).migrate(operation["app_id"], body.get("migration_plan", []))
            paths["data_dir"] = isolated.app_data_dir(operation["app_id"])
            paths["preview"] = True
        return BundleLauncher(self.config, runner=runner, checkpoint=runner.checkpoint).start(
            operation, delivery, **paths
        )

    def execute(self, operation_id):
        operation = self.platform.operation(operation_id)
        with self._guard:
            lock = self._apps.setdefault(
                operation["app_id"]
                if operation["kind"] in {"deploy", "stop", "destroy", "restore", "migrate"}
                else operation_id,
                Lock(),
            )
        with lock:
            operation = self.platform.operation(operation_id)
            if operation["status"] in TERMINAL:
                return operation
            runner = ContainerRunner(
                self.config, self.docker, checkpoint=lambda: self.checkpoint(operation), clock=self.clock
            )
            try:
                self.platform.claim(operation_id)
                kind = operation["kind"]
                body = operation["payload"]
                if kind == "prepare":
                    self.report(operation, "preparing")
                    if body.get("delivery", {}).get("mode") == "image":
                        delivery = {
                            "mode": "image",
                            "image_ref": body["delivery"]["image"],
                            "platform": body["platform"],
                            "startup": body["delivery"].get("startup", {}),
                        }
                        reference = delivery["image_ref"]
                        delivery["image_id"] = runner.ensure_image(
                            reference,
                            platform=delivery["platform"],
                            expected_id=reference if reference.startswith("sha256:") else None,
                        )
                    elif body.get("delivery", {}).get("mode") == "source-image":
                        from runtime_manager.legacy_prepare import prepare_image

                        delivery = prepare_image(
                            self.config,
                            self.platform,
                            self.docker,
                            operation,
                            checkpoint=runner.checkpoint,
                            report=lambda phase, **kwargs: self.report(operation, phase, **kwargs),
                        )
                    else:
                        delivery = BundlePreparer(self.config, self.platform, runner=runner).prepare(operation)
                    runner.cleanup(operation_id)
                    self.report(
                        operation, "completed", detail={"delivery": delivery, "stopped": True, "cleanup_complete": True}
                    )
                elif kind in {"probe", "preview"}:
                    if kind == "preview" and operation["stage"] == "serving":
                        self.checkpoint(operation)
                        bodies = self.executions(operation_id=operation_id)
                        if len(bodies) != 1 or not self.docker.inspect_container(bodies[0]["Id"]).get("State", {}).get(
                            "Running"
                        ):
                            raise ExecutionError("preview_execution_missing")
                        return
                    self.report(operation, "starting")
                    outcome = self._launch(operation, runner, preview=True)
                    self.report(operation, "ready", exec_ref=outcome["exec_ref"], detail=outcome)
                    if kind == "probe":
                        runner.cleanup(operation_id)
                        self.report(
                            operation, "completed", detail={"ready": True, "stopped": True, "cleanup_complete": True}
                        )
                    else:
                        return
                elif kind in {"deploy", "restore", "migrate"}:
                    self._deploy(operation, runner)
                elif kind in {"stop", "destroy"}:
                    self.stop_instances(operation)
                    for item in self.executions(app_id=operation["app_id"]):
                        if item.get("Labels", {}).get(PHASE_LABEL) == "serve":
                            self.docker.remove_container(item["Id"], force=False)
                    if kind == "destroy" and body.get("purge_volume"):
                        self.checkpoint(operation)
                        shutil.rmtree(
                            self.config.app_data_dir(operation["app_id"]), ignore_errors=False
                        ) if self.config.app_data_dir(operation["app_id"]).exists() else None
                        protected = self.config.data_root / "protected-backups" / operation["app_id"]
                        if protected.exists():
                            shutil.rmtree(protected)
                    self.report(operation, "completed", detail={"stopped": True, "cleanup_complete": True})
                else:
                    raise ExecutionError("operation_kind_unsupported")
            except Exception as exc:
                logger.exception("operation failed: %s (%s)", operation_id, type(exc).__name__)
                self._failure(operation, runner, exc)
            finally:
                try:
                    final = self.platform.operation(operation_id)
                    if final["status"] in TERMINAL and final.get("cleanup_status") == "complete":
                        scratch = self.config.data_root / "tasks" / operation_id
                        if scratch.exists():
                            shutil.rmtree(scratch)
                        preview = self.config.data_root / "previews" / operation_id
                        if preview.exists():
                            shutil.rmtree(preview)
                except Exception:
                    logger.exception("task scratch cleanup pending: %s", operation_id)

    def _deploy(self, operation, runner):
        body = operation["payload"]
        kind = operation["kind"]
        # The platform acknowledges maintenance before any writer is stopped.
        current = self.checkpoint(operation)
        if current["stage"] not in {"ready", "serving", "retiring"} and (
            body.get("uses_sqlite", True) or kind in {"restore", "migrate"}
        ):
            self.report(operation, "maintenance")
            self.stop_instances(operation, include_current=False)
            db = PlatformAppDb(self.config, self.platform, operation, checkpoint=runner.checkpoint)
            if kind == "restore":
                db.restore_confirmed(body["snapshot_id"])
            elif body.get("migration_plan"):
                snapshot = db.backup()
                self.report(operation, "snapshot_confirmed", detail={"snapshot": snapshot})
                self.report(operation, "migrating")
                db.migrate_confirmed(body["migration_plan"], snapshot=snapshot)
        if kind == "migrate" or (kind == "restore" and not body.get("resume_after_restore", True)):
            self.report(operation, "completed", detail={"stopped": True, "cleanup_complete": True})
            return
        current = self.checkpoint(operation)
        # A ready candidate survives an API reply loss and is adopted by its deterministic name.
        if current["stage"] not in {"serving", "retiring"}:
            if current["stage"] != "ready":
                self.report(operation, "starting")
            self.stop_instances(operation, include_current=False)
            outcome = self._launch(operation, runner)
            outcome["writers_stopped"] = bool(body.get("uses_sqlite", True))
            self.report(operation, "ready", exec_ref=outcome["exec_ref"], detail=outcome)
            while self.checkpoint(operation)["stage"] != "serving":
                self.clock.sleep(0.5)
        self.stop_instances(operation, include_current=False)
        for item in self.executions(app_id=operation["app_id"]):
            if (
                item.get("Labels", {}).get(PHASE_LABEL) == "serve"
                and item.get("Labels", {}).get(OP_LABEL) != operation["operation_id"]
            ):
                self.docker.remove_container(item["Id"], force=False)
        runner.cleanup(operation["operation_id"])
        self.report(operation, "completed", detail={"serving": True, "cleanup_complete": True})

    def _failure(self, operation, runner, exc):
        if isinstance(exc, ExecutionError) and str(exc) == "manager_stopping":
            return
        current = self.platform.operation(operation["operation_id"])
        if operation["kind"] in {"deploy", "restore"} and (
            current["stage"] in {"serving", "retiring"}
            or (current["status"] == "completed" and current.get("result", {}).get("serving"))
        ):
            logger.warning("committed serving operation retained for retirement retry: %s", operation["operation_id"])
            return
        unknown_build = current.get("payload", {}).get("legacy_build_state") == "started"
        if unknown_build and current["status"] in TERMINAL:
            return
        stopped = False
        complete = False
        try:
            # Only this operation's candidate is reclaimed; production data and old instances remain.
            for item in self.executions(operation_id=operation["operation_id"]):
                ident = item["Id"]
                if self.docker.inspect_container(ident).get("State", {}).get("Running"):
                    self.docker.stop_container(ident, timeout=self.config.stop_timeout_seconds)
                if self.docker.inspect_container(ident).get("State", {}).get("Running"):
                    raise ExecutionError("cleanup_pending")
                self.docker.remove_container(ident, force=False)
            stopped = not unknown_build
            complete = not unknown_build
        except Exception:
            logger.exception("operation cleanup pending: %s", operation["operation_id"])
        reason = (
            "legacy_build_stop_unconfirmed"
            if unknown_build
            else (str(exc) if isinstance(exc, ExecutionError) else "execution_failed")
        )
        phase = (
            current["status"]
            if current["status"] in TERMINAL
            else (
                "cancelled"
                if reason == "operation_cancelled"
                else "timed_out"
                if reason == "operation_timeout"
                else "failed"
            )
        )
        try:
            self.report(
                operation,
                phase,
                detail={
                    "reason": reason,
                    "diagnostic_tail": str(getattr(exc, "tail", ""))[-16384:],
                    "stopped": stopped,
                    "cleanup_complete": complete,
                    "failed_stage": current["stage"],
                    "maintenance": operation["kind"] in {"deploy", "restore", "migrate"}
                    and current["stage"] in {"maintenance", "snapshot_confirmed", "migrating", "starting", "ready"},
                    "data_may_have_changed": current["stage"] in {"migrating", "starting", "ready"}
                    and bool(operation["payload"].get("migration_plan") or operation["kind"] == "restore"),
                },
            )
        except Exception:
            logger.exception("cannot persist terminal operation fact: %s", operation["operation_id"])

    def heartbeat(self):
        info = self.docker.info()
        arch = {"aarch64": "arm64", "x86_64": "amd64"}.get(info.get("Architecture"), info.get("Architecture"))
        if info.get("OSType", "linux") != "linux":
            raise ExecutionError("unsupported_engine_os")

        def external_usage(item):
            details = self.docker.inspect_container(item["Id"])
            limits = details.get("HostConfig", {})
            committed = int(limits.get("Memory", 0))
            if not committed:
                memory_stats = self.docker.container_stats(item["Id"]).get("memory_stats", {})
                committed = max(
                    0, int(memory_stats.get("usage", 0)) - int(memory_stats.get("stats", {}).get("cache", 0))
                )
            return committed, int(limits.get("NanoCpus", 0)) // 1000000

        external = [
            item
            for item in self.docker.list_containers(all_states=False)
            if not (
                item.get("Labels", {}).get("bisheng.managed") == "v2"
                and item.get("Labels", {}).get("bisheng.runtime.node") == self.config.node_id
            )
            and item["Id"] not in getattr(self, "_legacy_owned", set())
        ]
        # Even one-shot Engine stats may wait for one sample. Bound concurrency
        # so a shared host's container count does not multiply heartbeat latency.
        with ThreadPoolExecutor(max_workers=8, thread_name_prefix="runtime-capacity") as samples:
            usage = list(samples.map(external_usage, external))
        external_memory = sum(memory for memory, _cpu in usage)
        external_cpu = sum(cpu for _memory, cpu in usage)
        memory = max(
            1,
            int(info["MemTotal"] // 1024 // 1024 * self.config.overcommit_ratio)
            - self.config.reserve_mb
            - (external_memory + 1024 * 1024 - 1) // (1024 * 1024),
        )
        cpu = max(1, int(info["NCPU"] * 1000 * self.config.overcommit_ratio) - external_cpu)
        self.platform.heartbeat(
            {
                "engine_id": info["ID"],
                "platform": "linux/" + arch,
                "memory_budget_mb": memory,
                "cpu_budget_millicores": cpu,
            }
        )

    def cleanup_data_workers(self):
        workers = self.docker.list_containers(
            all_states=True,
            filters={"label": ["bisheng.managed=data-helper", f"bisheng.runtime.node={self.config.node_id}"]},
        )
        protected = {item.get("Labels", {}).get("bisheng.runtime.operation") for item in workers}
        for item in workers:
            labels = item.get("Labels", {})
            deadline = int(labels.get("bisheng.runtime.deadline", "0"))
            if deadline > self.clock.time():
                continue
            ref = item["Id"]
            if self.docker.inspect_container(ref).get("State", {}).get("Running"):
                self.docker.stop_container(ref, timeout=5)
            if self.docker.inspect_container(ref).get("State", {}).get("Running"):
                continue
            self.docker.remove_container(ref, force=False)
            ident = labels.get("bisheng.runtime.operation", "")
            if len(ident) == 32 and all(c in "0123456789abcdef" for c in ident):
                output = self.config.data_root / "data-jobs" / ident
                if output.exists():
                    shutil.rmtree(output)

        root = self.config.data_root / "data-jobs"
        if root.exists():
            for output in root.iterdir():
                ident = output.name
                if (
                    len(ident) == 32
                    and all(c in "0123456789abcdef" for c in ident)
                    and ident not in protected
                    and output.is_dir()
                    and not output.is_symlink()
                    and output.stat().st_mtime < self.clock.time() - self.config.cleanup_seconds
                ):
                    shutil.rmtree(output)

    def reconcile(self):
        self.cleanup_data_workers()
        self.heartbeat()
        plan = self.platform.plan()
        live = {op["operation_id"] for op in plan}
        with self._guard:
            for ident, future in list(self._running.items()):
                if future.done():
                    self._running.pop(ident, None)
        for ident, future in list(self._observing.items()):
            if ident not in live and future.done():
                self._observing.pop(ident, None)
        self._legacy_owned = {op["payload"]["legacy_exec_ref"] for op in plan if op["payload"].get("legacy_exec_ref")}
        for op in plan:
            if op["status"] not in TERMINAL:
                self.submit(op["operation_id"])
            elif op["status"] == "completed" and op.get("execution"):
                future = self._observing.get(op["operation_id"])
                if future is None or future.done():
                    if future is not None:
                        try:
                            future.result()
                        except Exception:
                            logger.exception("runtime observation failed: %s", op["operation_id"])
                    self._observing[op["operation_id"]] = self._observers.submit(self.observe, op)
            elif op.get("cleanup_status") != "complete":
                self._failure(
                    op,
                    ContainerRunner(self.config, self.docker),
                    ExecutionError(op.get("failure", {}).get("reason", "execution_failed")),
                )

    def observe(self, op):
        import httpx

        execution = op["execution"]
        ref = execution["exec_ref"]
        running = False
        ready = False
        try:
            record = self.docker.inspect_container(ref)
            running = bool(record.get("State", {}).get("Running"))
            labels = record.get("Config", {}).get("Labels", {})
            if labels.get(OP_LABEL) != op["operation_id"] or labels.get("bisheng.runtime.node") != self.config.node_id:
                raise ExecutionError("execution_label_mismatch")
            if running:
                target = execution["target"]
                host = target["host"]
                host = f"[{host}]" if ":" in host else host
                response = httpx.get(
                    f"http://{host}:{target['port']}{op['payload'].get('health', {}).get('path', '/')}",
                    timeout=2,
                    trust_env=False,
                    follow_redirects=False,
                )
                ready = response.status_code < 500
        except httpx.HTTPError:
            logger.info("application readiness unavailable: %s", op["app_id"])
        except Exception as exc:
            if getattr(exc, "status_code", None) != 404:
                raise
        self.platform.observation(
            {
                "app_id": op["app_id"],
                "operation_id": op["operation_id"],
                "exec_ref": ref,
                "generation": op["generation"],
                "route_epoch": execution["route_epoch"],
                "running": running,
                "ready": ready,
            }
        )

    def close(self):
        self._closing.set()
        self._pool.shutdown(wait=False, cancel_futures=True)
        self._observers.shutdown(wait=False, cancel_futures=True)


class PlatformReconcileLoop:
    def __init__(self, executor):
        self.executor = executor
        self.stop_event = Event()
        self.thread = None

    def start(self):
        self.thread = Thread(target=self.run, name="runtime-v2-reconcile", daemon=True)
        self.thread.start()

    def run(self):
        while not self.stop_event.is_set():
            try:
                self.executor.reconcile()
            except Exception:
                logger.exception("platform reconciliation unavailable")
            self.stop_event.wait(self.executor.config.reconcile_interval_seconds)

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=5)
        self.executor.close()
