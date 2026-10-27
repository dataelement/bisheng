"""Docker execution and host filesystem behavior behind the runtime capability API."""

from __future__ import annotations

import logging
import shutil
import time
from concurrent.futures import ThreadPoolExecutor

from runtime_manager.bundle_launch import BundleLauncher
from runtime_manager.bundle_preparer import BundlePreparer
from runtime_manager.container_runner import OP_LABEL, PHASE_LABEL, ContainerRunner, ExecutionError
from runtime_manager.docker_backend import get_docker_backend

logger = logging.getLogger(__name__)


class DockerExecutor:
    def __init__(self, config, platform, docker=None, *, clock=time, checkpoint=None, report=None):
        self.config, self.platform = config, platform
        self.docker = docker or get_docker_backend()
        self.clock = clock
        self._checkpoint = checkpoint or (lambda operation: None)
        self._report = report or (lambda *args, **kwargs: None)

    def checkpoint(self, operation):
        return self._checkpoint(operation)

    def _runner(self, operation):
        return ContainerRunner(
            self.config, self.docker, checkpoint=lambda: self.checkpoint(operation), clock=self.clock
        )

    def capabilities(self):
        return {"executor_kind": "docker", "protocol_version": self.config.protocol_version, "host_filesystem": True}

    def prepare(self, operation):
        body = operation["payload"]
        runner = self._runner(operation)
        mode = body.get("delivery", {}).get("mode", "bundle")
        if mode == "image":
            reference = body["delivery"]["image"]
            return {
                "mode": "image",
                "image_ref": reference,
                "platform": body["platform"],
                "startup": body["delivery"].get("startup", {}),
                "image_id": runner.ensure_image(
                    reference,
                    platform=body["platform"],
                    expected_id=reference if reference.startswith("sha256:") else None,
                ),
            }
        if mode == "source-image":
            from runtime_manager.legacy_prepare import prepare_image

            return prepare_image(
                self.config,
                self.platform,
                self.docker,
                operation,
                checkpoint=runner.checkpoint,
                report=lambda phase, **kwargs: self._report(operation, phase, **kwargs),
            )
        return BundlePreparer(self.config, self.platform, runner=runner).prepare(operation)

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

    def launch(self, operation, runner=None, *, preview=False):
        runner = runner or self._runner(operation)
        preview = preview or operation["kind"] == "probe"
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

    def _record(self, exec_ref, operation=None):
        record = self.docker.inspect_container(exec_ref)
        labels = record.get("Config", {}).get("Labels", {})
        if labels.get("bisheng.runtime.node") != self.config.node_id or labels.get("bisheng.managed") != "v2":
            if not (
                operation
                and labels.get("bisheng.managed") == "true"
                and labels.get("bisheng.app.id") == operation["app_id"]
            ):
                raise ExecutionError("execution_scope_mismatch")
        if operation and labels.get("bisheng.app.id") != operation["app_id"]:
            raise ExecutionError("execution_scope_mismatch")
        return record

    def request_stop(self, exec_ref, operation):
        self.checkpoint(operation)
        record = self._record(exec_ref, operation)
        if record.get("State", {}).get("Running"):
            self.docker.stop_container(exec_ref, timeout=self.config.stop_timeout_seconds)
        return {"stopped": False, "reason": "stop_requested"}

    def confirm_stopped(self, exec_ref):
        try:
            record = self._record(exec_ref)
        except Exception as exc:
            if getattr(exc, "status_code", None) == 404:
                return {"stopped": False, "reason": "execution_missing"}
            raise
        stopped = not record.get("State", {}).get("Running", True)
        return {"stopped": stopped, "evidence_kind": "engine_stopped" if stopped else "unknown", "exec_ref": exec_ref}

    def cleanup(self, operation):
        for item in self.executions(operation_id=operation["operation_id"]):
            ident = item["Id"]
            record = self._record(ident, operation)
            if record.get("State", {}).get("Running"):
                self.docker.stop_container(ident, timeout=self.config.stop_timeout_seconds)
            if not self.confirm_stopped(ident)["stopped"]:
                return {"complete": False, "reason": "writer_stop_unconfirmed"}
            self.docker.remove_container(ident, force=False)
        return {"complete": True}

    def observe(self, exec_ref):
        import httpx

        record = self._record(exec_ref)
        labels = record.get("Config", {}).get("Labels", {})
        operation = self.platform.operation(labels[OP_LABEL])
        running = bool(record.get("State", {}).get("Running"))
        network = record.get("NetworkSettings", {}).get("Networks", {}).get(self.config.network, {})
        host = network.get("IPAddress") or network.get("GlobalIPv6Address") or ""
        port = int(operation["payload"].get("port", 8080))
        ready = False
        if running and host:
            path = operation["payload"].get("health", {}).get("path", "/")
            if not path.startswith("/") or any(c in path for c in "\r\n"):
                raise ExecutionError("health_path_invalid")
            address = f"[{host}]" if ":" in host else host
            try:
                ready = (
                    httpx.get(
                        f"http://{address}:{port}{path}", timeout=2, trust_env=False, follow_redirects=False
                    ).status_code
                    < 500
                )
            except httpx.HTTPError:
                pass
        return {"exec_ref": exec_ref, "running": running, "ready": ready, "target": {"host": host, "port": port}}

    def logs(self, exec_ref, *, since=None, tail=200):
        self._record(exec_ref)
        kwargs = {"tail": tail, "timestamps": True}
        if since is not None:
            kwargs["since"] = since
        return self.docker.container_logs(exec_ref, **kwargs)

    def data(self, operation, action, parameters):
        if action in {"backup", "migrate", "restore"}:
            from runtime_manager.platform_appdb import PlatformAppDb

            database = PlatformAppDb(
                self.config, self.platform, operation, checkpoint=lambda: self.checkpoint(operation)
            )
            if action == "backup":
                return database.backup()
            if action == "restore":
                return database.restore_confirmed(parameters["snapshot_id"])
            return database.migrate_confirmed(parameters["plan"], snapshot=parameters["snapshot"])
        if action == "purge":
            for root in (
                self.config.app_data_dir(operation["app_id"]),
                self.config.data_root / "protected-backups" / operation["app_id"],
            ):
                if root.exists():
                    shutil.rmtree(root)
            return {"purged": True}
        from runtime_manager.data_executor import DataExecutor

        return DataExecutor(self.config, self.docker, clock=self.clock).call(operation["app_id"], action, parameters)

    def cleanup_preparation(self, operation):
        return self._runner(operation).cleanup(operation["operation_id"])

    def retire_others(self, operation):
        for item in self.executions(app_id=operation["app_id"]):
            if (
                item.get("Labels", {}).get(PHASE_LABEL) == "serve"
                and item.get("Labels", {}).get(OP_LABEL) != operation["operation_id"]
            ):
                if self.docker.inspect_container(item["Id"]).get("State", {}).get("Running"):
                    raise ExecutionError("writer_stop_unconfirmed")
                self.docker.remove_container(item["Id"], force=False)

    def cleanup_local_scratch(self, operation):
        try:
            final = self.platform.operation(operation["operation_id"])
            if (
                final["status"] in {"completed", "failed", "cancelled", "timed_out"}
                and final.get("cleanup_status") == "complete"
            ):
                for path in (
                    self.config.data_root / "tasks" / operation["operation_id"],
                    self.config.data_root / "previews" / operation["operation_id"],
                ):
                    if path.exists():
                        shutil.rmtree(path)
        except Exception as exc:
            logger.error("task scratch cleanup pending: %s (%s)", operation["operation_id"], type(exc).__name__)
