"""Bounded preparation containers. No host shell, production mount or control secret."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from runtime_manager.bundle_inputs import BundleInputError
from runtime_manager.config import Config
from runtime_manager.docker_backend import get_docker_backend

logger = logging.getLogger(__name__)

OP_LABEL = "bisheng.runtime.operation"
PHASE_LABEL = "bisheng.runtime.phase"


class ExecutionError(RuntimeError):
    def __init__(self, reason, tail=""):
        super().__init__(reason)
        self.tail = tail


def host_path(config: Config, path: Path):
    root = config.data_root.resolve()
    path = Path(path).resolve()
    if not path.is_relative_to(root):
        raise BundleInputError("host_bind_scope_refused")
    return str((config.host_data_root or config.data_root) / path.relative_to(root))


def redact(text, env, sensitive_names=()):
    from runtime_manager.secret_redaction import redact_output

    return redact_output(text, env, sensitive_names)


class ContainerRunner:
    def __init__(self, config, docker=None, *, checkpoint=None, clock=time):
        self.config = config
        self.docker = docker or get_docker_backend()
        self.checkpoint = checkpoint or (lambda: None)
        self.clock = clock

    def ensure_image(self, reference, *, platform, expected_id=None):
        if self.config.image_pull_policy not in {"never", "if-not-present"}:
            raise BundleInputError("image_pull_policy_invalid")
        try:
            image = self.docker.inspect_image(expected_id or reference)
        except Exception as exc:
            if getattr(exc, "status_code", None) != 404 and not isinstance(exc, KeyError):
                raise
            if self.config.image_pull_policy == "never" or "@sha256:" not in reference:
                raise ExecutionError("image_missing") from exc
            self.checkpoint()
            self.docker.pull_image(reference)
            image = self.docker.inspect_image(reference)
        actual = image.get("Id", "")
        if expected_id and actual != expected_id:
            raise ExecutionError("image_content_mismatch")
        if f"{image.get('Os', 'linux')}/{image.get('Architecture', '')}" != platform:
            raise ExecutionError("image_platform_mismatch")
        if not expected_id and "@sha256:" in reference and reference not in (image.get("RepoDigests") or []):
            raise ExecutionError("image_digest_unavailable")
        if not actual.startswith("sha256:"):
            raise ExecutionError("image_identity_unavailable")
        return actual

    def run(
        self, operation, phase, *, image, command, mounts, env=None, network="none", timeout=None, uid=10001, gid=10001
    ):
        self.checkpoint()
        for directory, _target, readonly in mounts:
            if readonly:
                continue
            for path in [Path(directory), *Path(directory).rglob("*")]:
                if path.is_symlink():
                    continue
                stat = path.stat()
                if (stat.st_uid, stat.st_gid) != (uid, gid):
                    os.chown(path, uid, gid)
        env = env or {}
        timeout = timeout or self.config.task_timeout_seconds
        labels = {
            "bisheng.managed": "v2",
            OP_LABEL: operation["operation_id"],
            PHASE_LABEL: phase,
            "bisheng.runtime.node": self.config.node_id,
            "bisheng.app.id": operation["app_id"],
            "bisheng.runtime.epoch": str(operation["owner_epoch"]),
        }
        name = f"bisheng-v2-{operation['operation_id']}-{phase}"
        matches = self.docker.list_containers(
            all_states=True,
            filters={
                "label": [
                    f"bisheng.runtime.node={self.config.node_id}",
                    f"{OP_LABEL}={operation['operation_id']}",
                    f"{PHASE_LABEL}={phase}",
                ]
            },
        )
        if len(matches) > 1:
            raise ExecutionError("duplicate_execution_body")
        tier = operation.get("payload", {}).get("tier", {})
        memory = int(tier.get("memory_mb", 1024))
        cpu = int(tier.get("cpu_millicores", 1000))
        payload = {
            "Image": image,
            "Cmd": command,
            "Entrypoint": [],
            "User": f"{uid}:{gid}",
            "WorkingDir": "/workspace/app",
            "Env": [f"{key}={value}" for key, value in sorted(env.items())],
            "Labels": labels,
            "HostConfig": {
                "Binds": [
                    f"{host_path(self.config, path)}:{target}:{'ro' if readonly else 'rw'}"
                    for path, target, readonly in mounts
                ],
                "NetworkMode": network,
                "ReadonlyRootfs": True,
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges:true"],
                "PidsLimit": 256,
                "Memory": memory * 1024 * 1024,
                "MemorySwap": memory * 1024 * 1024,
                "NanoCpus": cpu * 1000000,
                "Tmpfs": {"/tmp": "rw,nosuid,nodev,size=512m"},
                "RestartPolicy": {"Name": "no"},
                "LogConfig": {"Type": "json-file", "Config": {"max-size": "10m", "max-file": "2"}},
            },
        }
        container = matches[0]["Id"] if matches else self.docker.create_container(name, payload)
        if not matches:
            self.docker.start_container(container)
        deadline = self.clock.monotonic() + timeout
        while True:
            self.checkpoint()
            state = self.docker.inspect_container(container).get("State", {})
            if not state.get("Running"):
                tail = redact(
                    self.docker.container_logs(container, tail=40),
                    env,
                    operation.get("payload", {}).get("sensitive_env_names", []),
                )[-16384:]
                if state.get("ExitCode", 1) != 0:
                    raise ExecutionError("preparation_process_failed", tail)
                return tail
            if self.clock.monotonic() >= deadline:
                self.docker.stop_container(container, timeout=self.config.stop_timeout_seconds)
                if self.docker.inspect_container(container).get("State", {}).get("Running"):
                    raise ExecutionError("cleanup_pending")
                raise ExecutionError("preparation_timeout")
            self.clock.sleep(0.2)

    def cleanup(self, operation_id):
        pending = []
        for item in self.docker.list_containers(
            all_states=True,
            filters={"label": [f"bisheng.runtime.node={self.config.node_id}", f"{OP_LABEL}={operation_id}"]},
        ):
            if item.get("Labels", {}).get(PHASE_LABEL) == "serve":
                continue
            ident = item["Id"]
            try:
                if self.docker.inspect_container(ident).get("State", {}).get("Running"):
                    self.docker.stop_container(ident, timeout=self.config.stop_timeout_seconds)
                if self.docker.inspect_container(ident).get("State", {}).get("Running"):
                    pending.append(ident)
                    continue
                self.docker.remove_container(ident, force=False)
            except Exception as exc:
                if getattr(exc, "status_code", None) == 404:
                    continue
                logger.exception("preparation cleanup failed for %s", ident)
                pending.append(ident)
        if pending:
            raise ExecutionError("cleanup_pending")
        return True

    def reset_phase(self, operation_id, phase):
        if phase == "serve":
            raise ExecutionError("cannot_reset_serving_instance")
        for item in self.docker.list_containers(
            all_states=True,
            filters={
                "label": [
                    f"bisheng.runtime.node={self.config.node_id}",
                    f"{OP_LABEL}={operation_id}",
                    f"{PHASE_LABEL}={phase}",
                ]
            },
        ):
            ref = item["Id"]
            if self.docker.inspect_container(ref).get("State", {}).get("Running"):
                self.docker.stop_container(ref, timeout=self.config.stop_timeout_seconds)
            if self.docker.inspect_container(ref).get("State", {}).get("Running"):
                raise ExecutionError("cleanup_pending")
            self.docker.remove_container(ref, force=False)
