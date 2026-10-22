"""Control SQLite filesystem access with a one-app mount, not a host path check."""

from __future__ import annotations

import json
import os
import shutil
import time
from threading import BoundedSemaphore, Lock
from uuid import uuid4

from fastapi import HTTPException

from runtime_manager.container_runner import ExecutionError, host_path
from runtime_manager.errors import DataBusyError

_slots = BoundedSemaphore(2)
_create_lock = Lock()


class DataExecutor:
    def __init__(self, config, docker, *, clock=time):
        self.config = config
        self.docker = docker
        self.clock = clock

    def payload(self, app_id, action, parameters, output, image, ident):
        uid = self.config.data_helper_uid
        gid = self.config.data_helper_gid
        return {
            "Image": image,
            "Entrypoint": [],
            "Cmd": [
                "python",
                "-m",
                "runtime_manager.data_worker",
                json.dumps({"app_id": app_id, "action": action, "parameters": parameters}, ensure_ascii=False),
            ],
            "User": f"{uid}:{gid}",
            "Env": ["PYTHONDONTWRITEBYTECODE=1"],
            "WorkingDir": "/app",
            "Labels": {
                "bisheng.managed": "data-helper",
                "bisheng.runtime.node": self.config.node_id,
                "bisheng.app.id": app_id,
                "bisheng.runtime.operation": ident,
                "bisheng.runtime.deadline": str(int(self.clock.time()) + 30),
            },
            "HostConfig": {
                "NetworkMode": "none",
                "ReadonlyRootfs": True,
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges:true"],
                "PidsLimit": 64,
                "Memory": 128 * 1024 * 1024,
                "MemorySwap": 128 * 1024 * 1024,
                "NanoCpus": 100000000,
                "RestartPolicy": {"Name": "no"},
                "Tmpfs": {"/tmp": "rw,nosuid,nodev,noexec,size=32m"},
                "LogConfig": {"Type": "json-file", "Config": {"max-size": "1m", "max-file": "1"}},
                "Binds": [
                    # WAL readers may create/lock sidecars even with SQL mode=ro.
                    # The trusted helper sees only this app; AppDbService keeps
                    # read actions on read-only SQLite connections.
                    f"{host_path(self.config, self.config.app_data_dir(app_id))}:/app-data/apps/{app_id}/db:rw",
                    f"{host_path(self.config, output)}:/app-data/exports:rw",
                ],
            },
        }

    def call(self, app_id, action, parameters):
        if not _slots.acquire(blocking=False):
            raise DataBusyError("Data maintenance capacity is busy")
        ref = None
        output = None
        preserve = False
        try:
            if self.config.reserve_mb < 256:
                raise DataBusyError("Data maintenance requires 256 MiB of reserved host capacity")
            if not self.config.data_helper_image:
                raise DataBusyError("Runtime data helper image is not configured")
            image = self.docker.inspect_image(self.config.data_helper_image)
            ident = uuid4().hex
            output = self.config.data_root / "data-jobs" / ident
            output.mkdir(parents=True, mode=0o700)
            os.chown(output, self.config.data_helper_uid, self.config.data_helper_gid)
            payload = self.payload(app_id, action, parameters, output, image["Id"], ident)
            with _create_lock:
                existing = self.docker.list_containers(
                    all_states=True,
                    filters={"label": ["bisheng.managed=data-helper", f"bisheng.runtime.node={self.config.node_id}"]},
                )
                if len(existing) >= 2:
                    raise DataBusyError("Data maintenance cleanup is pending")
                ref = self.docker.create_container("bisheng-data-" + ident, payload)
            self.docker.start_container(ref)
            deadline = self.clock.monotonic() + 30
            while self.docker.inspect_container(ref).get("State", {}).get("Running"):
                if self.clock.monotonic() > deadline:
                    raise ExecutionError("data_helper_timeout")
                self.clock.sleep(0.05)
            record = self.docker.inspect_container(ref)
            raw = self.docker.container_logs(ref, tail=1, timestamps=False)
            try:
                answer = json.loads(raw)
            except (ValueError, TypeError):
                raise DataBusyError("Data helper did not return a valid result") from None
            if answer.get("error"):
                raise HTTPException(status_code=answer.get("status_code", 400), detail=answer["error"])
            if record.get("State", {}).get("ExitCode") != 0:
                raise DataBusyError("Data helper failed")
            result = answer["result"]
            if action == "export":
                candidate = (output / result["file"]).resolve()
                if not candidate.is_relative_to(output.resolve()) or not candidate.is_file():
                    raise DataBusyError("Data export is unavailable")
                preserve = True
                return candidate, output
            return result
        finally:
            try:
                if ref:
                    if self.docker.inspect_container(ref).get("State", {}).get("Running"):
                        self.docker.stop_container(ref, timeout=5)
                    if self.docker.inspect_container(ref).get("State", {}).get("Running"):
                        raise ExecutionError("data_helper_cleanup_pending")
                    self.docker.remove_container(ref, force=False)
                if output and output.exists() and not preserve:
                    shutil.rmtree(output)
            finally:
                _slots.release()
