"""Restricted launch payload for prebuilt runtimes, full images and legacy results."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import httpx

from runtime_manager.admission import Tier
from runtime_manager.bundle_inputs import BundleInputError, startup_command
from runtime_manager.container_runner import OP_LABEL, PHASE_LABEL, ContainerRunner, ExecutionError, host_path
from runtime_manager.lifecycle import build_container_payload

logger = logging.getLogger(__name__)


class BundleLauncher:
    def __init__(self, config, docker=None, *, runner=None, checkpoint=None, http_get=None, clock=time):
        self.config = config
        self.runner = runner or ContainerRunner(config, docker, checkpoint=checkpoint)
        self.docker = self.runner.docker
        self.checkpoint = checkpoint or (lambda: None)
        self.clock = clock
        self.http_get = http_get or (
            lambda url: httpx.get(url, timeout=2, trust_env=False, follow_redirects=False).status_code
        )

    def payload(self, operation, delivery, *, code_dir=None, environment_dir=None, data_dir=None, preview=False):
        body = operation["payload"]
        profile = delivery.get("profile", {})
        platform = delivery.get("platform") or profile.get("platform")
        mode = delivery["mode"]
        reference = delivery.get("image_ref") or profile.get("runtime_image")
        image = self.runner.ensure_image(
            reference, platform=platform, expected_id=delivery.get("image_id") or profile.get("runtime_image_id")
        )
        port = int(body.get("port", 8080))
        health = body.get("health", {})
        tier = body.get("tier", {})
        env = dict(body.get("runtime_env", {}))
        if any(
            key.startswith(("RTM_", "APP_PROXY_"))
            or key in {"DOCKER_HOST", "BISHENG_RUNTIME_SERVICE_KEYS", "BISHENG_RUNTIME_PAYLOAD_KEY"}
            for key in env
        ):
            raise BundleInputError("control_secret_environment_refused")
        env.update(
            {
                "PORT": str(port),
                "BISHENG_APP_PORT": str(port),
                "BISHENG_APP_ID": operation["app_id"],
                "BISHENG_APP_DB_URL": "sqlite:////data/app.db",
                "BISHENG_APP_BASE_PATH": body.get("base_path", f"/apps/{body.get('slug', operation['app_id'])}"),
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )
        if mode == "bundle" and profile.get("language") == "python3.11":
            env["PATH"] = "/opt/venv/bin:/usr/local/bin:/usr/bin:/bin"
        command = delivery.get("startup", {}).get("command")
        if mode == "bundle":
            command = startup_command(Path(code_dir), profile["language"], command)
        payload = build_container_payload(
            self.config,
            app_id=operation["app_id"],
            slug=body.get("slug", operation["app_id"]),
            version_id=operation.get("version_id", ""),
            version_no=int(body.get("version_no", 1)),
            image_ref=image,
            tier=Tier(cpu=int(tier.get("cpu_millicores", 1000)) / 1000, mem_mb=int(tier.get("memory_mb", 1024))),
            port=port,
            health_path=health.get("path", "/"),
            health_interval=int(health.get("interval", 10)),
            health_timeout=int(health.get("timeout", 3)),
            health_retries=int(health.get("retries", 3)),
            start_period=int(health.get("start_period", 20)),
            env=env,
            generation=operation["generation"],
        )
        payload.pop("Healthcheck", None)
        if command:
            payload["Cmd"] = command
            if mode == "image":
                payload["Entrypoint"] = []
        payload["User"] = f"{profile.get('uid', 10001)}:{profile.get('gid', 10001)}"
        payload["WorkingDir"] = "/workspace/app" if mode == "bundle" else delivery.get("working_dir", "")
        if not payload["WorkingDir"]:
            payload.pop("WorkingDir")
        payload["Labels"].update(
            {
                "bisheng.managed": "v2",
                OP_LABEL: operation["operation_id"],
                PHASE_LABEL: "probe" if preview else "serve",
                "bisheng.runtime.node": self.config.node_id,
                "bisheng.runtime.epoch": str(operation["owner_epoch"]),
            }
        )
        data_dir = Path(data_dir) if data_dir else self.config.app_data_dir(operation["app_id"])
        data_dir.mkdir(parents=True, exist_ok=True)
        binds = [f"{host_path(self.config, data_dir)}:/data:rw"]
        if mode == "bundle":
            binds.append(f"{host_path(self.config, Path(code_dir))}:/workspace/app:ro")
            if environment_dir:
                target = "/opt/venv" if profile["language"] == "python3.11" else "/workspace/app/node_modules"
                binds.append(f"{host_path(self.config, Path(environment_dir))}:{target}:ro")
        payload["HostConfig"].update(
            {"Binds": binds, "CapDrop": ["ALL"], "PidsLimit": 256, "RestartPolicy": {"Name": "no"}}
        )
        return payload

    def start(self, operation, delivery, **paths):
        self.checkpoint()
        payload = self.payload(operation, delivery, **paths)
        uid, gid = map(int, payload["User"].split(":"))
        data_dir = Path(paths.get("data_dir") or self.config.app_data_dir(operation["app_id"]))
        if data_dir.is_symlink():
            raise ExecutionError("data_directory_link_refused")
        for path in [
            data_dir,
            *[data_dir / name for name in ("app.db", "app.db-wal", "app.db-shm") if (data_dir / name).exists()],
        ]:
            if path.is_symlink():
                raise ExecutionError("database_link_refused")
            stat = path.stat()
            if (stat.st_uid, stat.st_gid) != (uid, gid):
                os.chown(path, uid, gid)
        name = f"bisheng-v2-{operation['operation_id']}-{'probe' if paths.get('preview') else 'serve'}"
        matches = self.docker.list_containers(
            all_states=True,
            filters={
                "label": [
                    f"bisheng.runtime.node={self.config.node_id}",
                    f"{OP_LABEL}={operation['operation_id']}",
                    f"{PHASE_LABEL}={payload['Labels'][PHASE_LABEL]}",
                ]
            },
        )
        if len(matches) > 1:
            raise ExecutionError("duplicate_execution_body")
        ref = matches[0]["Id"] if matches else self.docker.create_container(name, payload)
        if not matches:
            self.docker.start_container(ref)
        return self.wait_ready(operation, ref)

    def wait_ready(self, operation, ref):
        body = operation["payload"]
        port = int(body.get("port", 8080))
        path = body.get("health", {}).get("path", "/")
        if not path.startswith("/") or "\r" in path or "\n" in path:
            raise BundleInputError("health_path_invalid")
        deadline = self.clock.monotonic() + self.config.probe_timeout_seconds
        while True:
            self.checkpoint()
            record = self.docker.inspect_container(ref)
            if not record.get("State", {}).get("Running"):
                raise ExecutionError("startup_exited")
            network = record.get("NetworkSettings", {}).get("Networks", {}).get(self.config.network, {})
            host = network.get("IPAddress") or network.get("GlobalIPv6Address")
            if host:
                url = f"http://[{host}]:{port}{path}" if ":" in host else f"http://{host}:{port}{path}"
                try:
                    if self.http_get(url) < 500:
                        return {
                            "exec_ref": ref,
                            "phase": "running",
                            "target": {"host": host, "port": port},
                            "generation": operation["generation"],
                            "version_id": operation.get("version_id", ""),
                        }
                except httpx.HTTPError as exc:
                    logger.debug("readiness request failed; retrying: %s", type(exc).__name__)
            if self.clock.monotonic() >= deadline:
                raise ExecutionError("readiness_timeout")
            self.clock.sleep(self.config.probe_interval_seconds)
