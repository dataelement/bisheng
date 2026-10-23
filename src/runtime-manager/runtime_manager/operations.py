"""Platform-owned operation executor. Local locks supplement persistent fencing."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Event, Lock, Thread

from runtime_manager.container_runner import OP_LABEL, PHASE_LABEL, ExecutionError
from runtime_manager.docker_backend import get_docker_backend
from runtime_manager.executors.docker import DockerExecutor
from runtime_manager.executors.protocol import ExecutorError
from runtime_manager.platform_client import PlatformClient, PlatformError

logger = logging.getLogger(__name__)
TERMINAL = {"completed", "failed", "cancelled", "timed_out"}


class OperationExecutor:
    def __init__(self, config, platform=None, docker=None, *, clock=time, runtime=None):
        self.config = config
        self.platform = platform or PlatformClient(config)
        self.docker = None
        self.clock = clock
        self._closing = Event()
        self._guard = Lock()
        self._apps = {}
        self._running = {}
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="runtime-v2")
        self._observers = ThreadPoolExecutor(max_workers=2, thread_name_prefix="runtime-observe")
        self._observing = {}
        if runtime is not None:
            self.runtime = runtime
            self.docker = getattr(runtime, "docker", None)
        elif config.executor_kind == "kubernetes":
            from runtime_manager.executors.kubernetes import KubernetesExecutor
            from runtime_manager.k8s_config import KubernetesConfig
            from runtime_manager.k8s_data_executor import KubernetesDataExecutor

            self.runtime = KubernetesExecutor(
                config,
                KubernetesConfig.from_env(),
                platform=self.platform,
                clock=clock,
                checkpoint=self.process_checkpoint,
            )
            self.runtime.data_transport = KubernetesDataExecutor(self.runtime)
        else:
            self.docker = docker or get_docker_backend()
            self.runtime = DockerExecutor(
                config, self.platform, self.docker, clock=clock, checkpoint=self.checkpoint, report=self.report
            )

    def process_checkpoint(self):
        if self._closing.is_set():
            raise ExecutorError("manager_stopping")

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
        if datetime.fromtimestamp(self.clock.time(), UTC) >= deadline:
            raise ExecutionError("operation_timeout")
        return current

    def report(self, operation, phase, *, exec_ref="", detail=None):
        # Retries query the committed sequence, never guess whether a fact was accepted.
        current = self.platform.operation(operation["operation_id"])
        detail = dict(detail or {})
        for key in ("prepare_progress", "maintenance_progress", "prepared_delivery"):
            if key not in detail and key in current.get("result", {}):
                detail[key] = current["result"][key]
        if self.config.executor_kind == "kubernetes":
            detail["controller"] = self.runtime._controller()
        return self.platform.fact(
            operation, int(current.get("fact_sequence", 0)) + 1, phase, exec_ref=exec_ref, detail=detail
        )

    def _wait_cleanup(self, operation, cleanup):
        while True:
            self.checkpoint(operation)
            if self.config.executor_kind == "kubernetes":
                self.runtime._controller()
            if cleanup().get("complete"):
                self.checkpoint(operation)
                return
            self.clock.sleep(0.5)

    def _prepared_delivery(self, operation):
        current = self.checkpoint(operation)
        saved = current.get("result", {})
        if "prepared_delivery" in saved:
            delivery = saved["prepared_delivery"]
            if not isinstance(delivery, dict) or not delivery:
                raise ExecutorError("prepared_delivery_invalid")
            return delivery
        self.report(operation, "preparing")
        delivery = self.runtime.prepare(operation)
        if not isinstance(delivery, dict) or not delivery:
            raise ExecutorError("prepared_delivery_invalid")
        self.checkpoint(operation)
        try:
            self.report(operation, "preparing", detail={"prepared_delivery": delivery})
        except PlatformError:
            # An acknowledged SQL result is required before cleanup may remove its producers.
            saved = self.platform.operation(operation["operation_id"]).get("result", {})
            if saved.get("prepared_delivery") != delivery:
                raise
            self.checkpoint(operation)
        return delivery

    def executions(self, app_id=None, operation_id=None):
        return self.runtime.executions(app_id=app_id, operation_id=operation_id)

    def stop_instances(self, operation, *, include_current=True):
        if self.config.executor_kind == "docker":
            return self.runtime.stop_instances(operation, include_current=include_current)
        operations = self.platform.node_snapshot()["operations"]
        scope = self.platform.application(operation["app_id"])
        if scope.get("operation_id") and not any(op["operation_id"] == scope["operation_id"] for op in operations):
            operations.append(self.platform.operation(scope["operation_id"]))
        for old in operations:
            if old["app_id"] != operation["app_id"] or (
                not include_current and old["operation_id"] == operation["operation_id"]
            ):
                continue
            resources = self.platform.resources(old["operation_id"])
            pods = [
                row
                for row in resources
                if row["kind"] == "Pod"
                and (
                    operation["kind"] == "destroy" or row["purpose"] in {"serve", "migrate", "restore", "data", "purge"}
                )
            ]
            if not pods:
                continue
            for row in pods:
                if row.get("stop_state") == "confirmed" and row.get("cleanup_state") == "complete":
                    continue
                self.checkpoint(operation)
                self.runtime._controller()
                self.runtime.request_stop(row["resource_ref"], operation)
                deadline = self.clock.time() + 60
                while True:
                    self.checkpoint(operation)
                    self.runtime._controller()
                    if self.runtime.confirm_stopped(row["resource_ref"])["stopped"]:
                        break
                    if self.clock.time() >= deadline:
                        raise ExecutorError("writer_stop_unconfirmed")
                    self.clock.sleep(0.5)
            self._wait_cleanup(operation, lambda old=old: self.runtime.cleanup(old))

    def _launch(self, operation, runner=None, *, preview=False):
        if self.config.executor_kind == "docker":
            return self.runtime.launch(operation, runner=runner, preview=preview)
        return self.runtime.launch(operation, preview=preview)

    def execute(self, operation_id):
        operation = self.platform.operation(operation_id)
        with self._guard:
            lock = self._apps.setdefault(
                operation["app_id"]
                if operation["kind"] in {"deploy", "stop", "destroy", "restore", "migrate", "data"}
                else operation_id,
                Lock(),
            )
        with lock:
            operation = self.platform.operation(operation_id)
            if operation["status"] in TERMINAL:
                return operation
            try:
                self.platform.claim(operation_id)
                kind, body = operation["kind"], operation["payload"]
                if kind == "prepare":
                    delivery = self._prepared_delivery(operation)
                    self._wait_cleanup(operation, lambda: self.runtime.cleanup(operation))
                    self.report(
                        operation, "completed", detail={"delivery": delivery, "stopped": True, "cleanup_complete": True}
                    )
                elif kind in {"probe", "preview"}:
                    if kind == "preview" and operation["stage"] == "serving":
                        self.checkpoint(operation)
                        execution = operation.get("execution") or {}
                        if not execution.get("exec_ref") or not self.runtime.observe(execution["exec_ref"]).get(
                            "running", True
                        ):
                            raise ExecutorError("preview_execution_missing")
                        return
                    current = self.checkpoint(operation)
                    if kind != "probe" or current["stage"] != "ready":
                        self.report(operation, "starting")
                        outcome = self._launch(operation, preview=(kind == "preview"))
                        self.report(operation, "ready", exec_ref=outcome["exec_ref"], detail=outcome)
                    if kind == "probe":
                        self._wait_cleanup(operation, lambda: self.runtime.cleanup(operation))
                        self.report(
                            operation, "completed", detail={"ready": True, "stopped": True, "cleanup_complete": True}
                        )
                elif kind == "data":
                    current = self.checkpoint(operation)
                    state = current["payload"].get("data_action_finished")
                    if not state:
                        self.report(operation, "starting")
                        target = self.runtime.data(operation, "prepare-session", {})
                        self.report(operation, "ready", exec_ref=target["exec_ref"], detail={"data_target": target})
                        while True:
                            current = self.checkpoint(operation)
                            state = current["payload"].get("data_action_finished")
                            if state:
                                break
                            self.clock.sleep(0.1)
                    self._wait_cleanup(operation, lambda: self.runtime.data(current, "finish-session", {}))
                    self.report(
                        operation,
                        "completed" if state == "done" else "failed",
                        detail={
                            "data_session": True,
                            "stopped": True,
                            "cleanup_complete": True,
                            **(
                                {}
                                if state == "done"
                                else {"reason": "data_result_unknown" if state == "unknown" else "data_action_failed"}
                            ),
                        },
                    )
                elif kind in {"deploy", "restore", "migrate"}:
                    self._deploy(operation)
                elif kind in {"stop", "destroy"}:
                    self.stop_instances(operation, include_current=not (kind == "destroy" and body.get("purge_volume")))
                    if self.config.executor_kind == "docker":
                        # The adapter owns container and filesystem deletion.
                        for item in self.runtime.executions(app_id=operation["app_id"]):
                            if item.get("Labels", {}).get(PHASE_LABEL) == "serve":
                                previous = self.platform.operation(item["Labels"][OP_LABEL])
                                self._wait_cleanup(operation, lambda previous=previous: self.runtime.cleanup(previous))
                    if kind == "destroy" and body.get("purge_volume"):
                        self.checkpoint(operation)
                        self.runtime.data(operation, "purge", {})
                    self.report(operation, "completed", detail={"stopped": True, "cleanup_complete": True})
                else:
                    raise ExecutionError("operation_kind_unsupported")
            except Exception as exc:
                logger.error("operation failed: %s (%s)", operation_id, type(exc).__name__)
                self._failure(operation, None, exc)
            finally:
                if self.config.executor_kind == "docker":
                    self.runtime.cleanup_local_scratch(operation)

    def _deploy(self, operation, runner=None):
        body, kind = operation["payload"], operation["kind"]
        current = self.checkpoint(operation)
        if current["stage"] not in {"ready", "serving", "retiring"} and (
            body.get("uses_sqlite", True) or kind in {"restore", "migrate"}
        ):
            self.report(operation, "maintenance")
            self.stop_instances(operation, include_current=False)
            if kind == "restore":
                self.runtime.data(operation, "restore", {"snapshot_id": body["snapshot_id"]})
            elif body.get("migration_plan"):
                snapshot = self.runtime.data(operation, "backup", {})
                self.report(operation, "snapshot_confirmed", detail={"snapshot": snapshot})
                self.report(operation, "migrating")
                self.runtime.data(operation, "migrate", {"plan": body["migration_plan"], "snapshot": snapshot})
        if kind == "migrate" or (kind == "restore" and not body.get("resume_after_restore", True)):
            self.report(operation, "completed", detail={"stopped": True, "cleanup_complete": True})
            return
        current = self.checkpoint(operation)
        if current["stage"] not in {"serving", "retiring"}:
            if current["stage"] != "ready":
                self.report(operation, "starting")
            self.stop_instances(operation, include_current=False)
            outcome = self._launch(operation, runner)
            outcome["writers_stopped"] = True
            self.report(operation, "ready", exec_ref=outcome["exec_ref"], detail=outcome)
            while self.checkpoint(operation)["stage"] != "serving":
                self.clock.sleep(0.5)
        self.stop_instances(operation, include_current=False)
        if self.config.executor_kind == "docker":
            self.runtime.retire_others(operation)
            self.runtime.cleanup_preparation(operation)
        self.report(operation, "completed", detail={"serving": True, "cleanup_complete": True})

    def _stop_cleanup_checkpoint(self, operation):
        self.process_checkpoint()
        self.runtime._controller()
        current = self.platform.operation(operation["operation_id"])
        keys = ("operation_id", "app_id", "node_id", "generation", "owner_epoch", "kind", "deadline")
        if any(current.get(key) != operation.get(key) for key in keys):
            raise ExecutorError("execution_fence_mismatch")
        if (
            current["status"] != "timed_out"
            or current.get("cleanup_status") != "pending"
            or current.get("failure", {}).get("reason") != "operation_timeout"
        ):
            raise ExecutorError("stop_cleanup_state_unconfirmed")
        scope = self.platform.application(operation["app_id"])
        if any(scope.get(key) != operation.get(key) for key in ("app_id", "node_id", "generation", "owner_epoch")) or (
            scope.get("phase") != "stopped"
        ):
            raise ExecutorError("stop_cleanup_scope_changed")
        return scope

    def _expired_stop_cleanup(self, operation, current, exc):
        if any(
            current.get(key) != operation.get(key)
            for key in ("operation_id", "app_id", "node_id", "generation", "owner_epoch", "kind", "deadline")
        ):
            raise ExecutorError("execution_fence_mismatch")
        failure = (
            current.get("failure", {})
            if current["status"] in TERMINAL
            else {
                "reason": "operation_timeout",
                "diagnostic_tail": str(getattr(exc, "tail", ""))[-16384:],
                "failed_stage": current["stage"],
                "maintenance": False,
                "data_may_have_changed": False,
            }
        )
        # A terminal pending fact keeps the active assignment fenced. Its ACK
        # must precede cleanup; an unknown reply is retried only on a later pass.
        receipt = self.report(operation, "timed_out", detail={**failure, "stopped": False, "cleanup_complete": False})
        if (
            not isinstance(receipt, dict)
            or any(
                receipt.get(key) != operation.get(key)
                for key in ("operation_id", "node_id", "generation", "owner_epoch")
            )
            or receipt.get("phase") != "timed_out"
        ):
            raise ExecutorError("stop_cleanup_receipt_unconfirmed")
        scope = self._stop_cleanup_checkpoint(operation)
        sources = self.platform.node_snapshot()["operations"]
        origin = scope.get("operation_id")
        if origin and not any(old["operation_id"] == origin for old in sources):
            sources.append(self.platform.operation(origin))
        cleanup = []
        found_route = not origin and not scope.get("exec_ref")
        for old in sources:
            if old["app_id"] != operation["app_id"] or old["operation_id"] == operation["operation_id"]:
                continue
            rows = self.platform.resources(old["operation_id"])
            writers = [
                row
                for row in rows
                if row["kind"] == "Pod" and row["purpose"] in {"serve", "migrate", "restore", "data", "purge"}
            ]
            if not writers:
                continue
            if (
                old["status"] not in TERMINAL
                or old.get("node_id") != operation["node_id"]
                or type(old.get("generation")) is not int
                or not 0 < old["generation"] <= operation["generation"]
                or type(old.get("owner_epoch")) is not int
                or not 0 < old["owner_epoch"] <= operation["owner_epoch"]
            ):
                raise ExecutorError("stop_cleanup_source_unconfirmed")
            for row in rows:
                if any(row.get(key) != old.get(key) for key in ("app_id", "node_id", "generation", "owner_epoch")) or (
                    row.get("operation_id") != old["operation_id"]
                ):
                    raise ExecutorError("stop_cleanup_resource_scope_changed")
                if row["kind"] != "Pod" or (
                    row.get("stop_state") == "confirmed" and row.get("cleanup_state") == "complete"
                ):
                    continue
                if (
                    not isinstance(row.get("uid"), str)
                    or not row["uid"]
                    or row.get("stop_state") not in {"held", "requested", "confirmed"}
                    or row.get("cleanup_state") not in {"pending", "complete"}
                ):
                    raise ExecutorError("stop_cleanup_writer_unconfirmed")
            if old["operation_id"] == origin:
                found_route = any(row["resource_ref"] == scope.get("exec_ref") for row in writers)
            cleanup.append(old)
        if not found_route:
            raise ExecutorError("stop_cleanup_route_unconfirmed")
        complete = True
        for old in cleanup:
            # Existing terminal-own cleanup authority only; never authorize an
            # expired stop to mutate another operation's resources.
            self._stop_cleanup_checkpoint(operation)
            complete = bool(self.runtime.cleanup(old).get("complete")) and complete
        if complete:
            self._stop_cleanup_checkpoint(operation)
            self.report(operation, "timed_out", detail={**failure, "stopped": True, "cleanup_complete": True})

    def _failure(self, operation, runner, exc):
        if isinstance(exc, (ExecutionError, ExecutorError)) and str(exc) == "manager_stopping":
            return
        current = self.platform.operation(operation["operation_id"])
        if operation["kind"] in {"deploy", "restore"} and (
            current["stage"] in {"serving", "retiring"}
            or (current["status"] == "completed" and current.get("result", {}).get("serving"))
        ):
            logger.warning("committed serving operation retained for retirement retry: %s", operation["operation_id"])
            return
        kubernetes_stop = self.config.executor_kind == "kubernetes" and operation["kind"] == "stop"
        if kubernetes_stop:
            if current["status"] in TERMINAL and current.get("cleanup_status") == "complete":
                return
            deadline = datetime.fromisoformat(current["deadline"].replace("Z", "+00:00"))
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=UTC)
            expired = datetime.fromtimestamp(self.clock.time(), UTC) >= deadline
            timeout = expired and (
                (isinstance(exc, PlatformError) and exc.status == 409 and str(exc) == "operation_expired")
                or (isinstance(exc, (ExecutionError, ExecutorError)) and str(exc) == "operation_timeout")
            )
            if (current["status"] not in TERMINAL and timeout) or (
                current["status"] == "timed_out"
                and current.get("cleanup_status") == "pending"
                and current.get("failure", {}).get("reason") == "operation_timeout"
            ):
                try:
                    self._expired_stop_cleanup(operation, current, exc)
                except Exception as cleanup_error:
                    logger.error(
                        "expired stop cleanup pending: %s (%s)", operation["operation_id"], type(cleanup_error).__name__
                    )
                return
            if current["status"] not in TERMINAL:
                # Uncertain control results must not strand a durable stop in
                # failed/pending. A later pass retries within its original fence.
                return
        unknown_build = current.get("payload", {}).get("legacy_build_state") == "started"
        if unknown_build and current["status"] in TERMINAL:
            return
        stopped = complete = False
        try:
            # A stop owns no serving Pod itself; its empty resource set cannot
            # prove that application writers from earlier deployments stopped.
            complete = (
                not kubernetes_stop and bool(self.runtime.cleanup(operation).get("complete")) and not unknown_build
            )
            stopped = complete
        except Exception as cleanup_error:
            logger.error("operation cleanup pending: %s (%s)", operation["operation_id"], type(cleanup_error).__name__)
        reason = (
            "legacy_build_stop_unconfirmed"
            if unknown_build
            else (str(exc) if isinstance(exc, (ExecutionError, ExecutorError)) else "execution_failed")
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
        failure = {
            "reason": reason,
            "diagnostic_tail": str(getattr(exc, "tail", ""))[-16384:],
            "failed_stage": current["stage"],
            "maintenance": operation["kind"] in {"deploy", "restore", "migrate"}
            and current["stage"] in {"maintenance", "snapshot_confirmed", "migrating", "starting", "ready"},
            "data_may_have_changed": current["stage"] in {"migrating", "starting", "ready"}
            and bool(operation["payload"].get("migration_plan") or operation["kind"] == "restore"),
        }
        if current["status"] in TERMINAL:
            # Cleanup progress must not replace the original failure or revive expired diagnostics.
            failure = {key: value for key, value in current.get("failure", {}).items() if key in failure}
        try:
            self.report(
                operation,
                phase,
                detail={**failure, "stopped": stopped, "cleanup_complete": complete},
            )
        except Exception as report_error:
            logger.error(
                "cannot persist terminal fact: %s (%s)", operation["operation_id"], type(report_error).__name__
            )

    def heartbeat(self):
        if self.config.executor_kind == "docker":
            self.runtime._legacy_owned = getattr(self, "_legacy_owned", set())
            return self.runtime.heartbeat()
        descriptor = self.runtime.descriptor
        snapshot = getattr(self.runtime, "heartbeat_snapshot", None)
        if callable(snapshot):
            observed = snapshot()
            capabilities, probe = observed["capabilities"], observed["probe_report"]
        else:
            capabilities = self.runtime.capabilities()
            probe = self.runtime.probe_report()
        probe["ready"] = probe.get("ready") is True and capabilities.get("orchestration_available") is True
        self.platform.heartbeat(
            {
                "engine_id": descriptor.cluster_id + "/" + descriptor.namespace,
                "platform": descriptor.platform,
                "memory_budget_mb": descriptor.memory_budget_mb,
                "cpu_budget_millicores": descriptor.cpu_budget_millicores,
                "executor_kind": "kubernetes",
                "capabilities": capabilities,
                "probe_report": probe,
            }
        )

    def cleanup_data_workers(self):
        if self.config.executor_kind == "docker":
            return self.runtime.cleanup_data_workers()
        transport = getattr(self.runtime, "data_transport", None)
        if transport is not None:
            transport.cleanup_exports()

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
                    None,
                    ExecutionError(op.get("failure", {}).get("reason", "execution_failed")),
                )

    def observe(self, op):
        execution = op["execution"]
        try:
            result = self.runtime.observe(execution["exec_ref"])
        except Exception as exc:
            if getattr(exc, "status_code", None) != 404:
                raise
            result = {"running": False, "ready": False}
        self.platform.observation(
            {
                "app_id": op["app_id"],
                "operation_id": op["operation_id"],
                "exec_ref": execution["exec_ref"],
                "generation": op["generation"],
                "route_epoch": execution["route_epoch"],
                "running": result.get("running", result.get("phase") == "Running"),
                "ready": result["ready"],
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
