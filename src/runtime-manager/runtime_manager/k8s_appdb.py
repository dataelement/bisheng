"""Trusted maintenance of an exclusively held volume through delegated materials.

SQLite is still owned by appdb. This adapter changes its volume/transport ports;
no platform HMAC, MinIO credential, or arbitrary SQL enters the maintenance Pod.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
from uuid import UUID, uuid4

from runtime_manager.appdb import PlatformAppDb
from runtime_manager.config import Config
from runtime_manager.container_runner import ExecutionError
from runtime_manager.k8s_data_helper import VolumeDatabase


def _directory(path):
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise ExecutionError("maintenance_layout_link_refused")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def _sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class MaterialPort:
    def __init__(self, client):
        self.client = client

    def upload(self, operation_id, path, *, kind, metadata):
        return self.client.upload(path, kind=kind, metadata=metadata)

    def download(self, operation_id, artifact_id, target):
        manifest = self.client.describe(artifact_id)
        if manifest.get("kind") != "snapshot":
            raise ExecutionError("snapshot_type_required")
        self.client.download(
            artifact_id,
            target,
            expected_sha256=manifest["sha256"],
            expected_size=manifest["size_bytes"],
            max_bytes=10 * 1024**3,
        )
        return manifest


class VolumeMaintenance(PlatformAppDb):
    def __init__(self, volume, operation, client):
        self.volume = Path(volume)
        _directory(self.volume)
        _directory(self.volume / "business")
        _directory(self.volume / "platform")
        self.database = VolumeDatabase(self.volume, operation["app_id"])
        super().__init__(Config(data_root=self.volume / "platform"), MaterialPort(client), operation)

    def db_path(self, app_id):
        try:
            return self.database.db_path(app_id)
        except Exception:
            raise ExecutionError("maintenance_database_link_refused") from None

    def _handoff(self, path):
        # The installer freezes one non-root UID/GID for app and trusted helper.
        if path.exists() and path.stat().st_uid != os.geteuid():
            raise ExecutionError("maintenance_database_owner_mismatch")


def run_maintenance(document, client, *, volume=Path("/volume")):
    if not isinstance(document, dict) or set(document) != {"operation", "action", "parameters"}:
        raise ExecutionError("maintenance_document_invalid")
    operation, action, parameters = document["operation"], document["action"], document["parameters"]
    if action not in {"backup", "migrate", "restore"} or not isinstance(parameters, dict):
        raise ExecutionError("maintenance_action_invalid")
    try:
        operation_id = operation["operation_id"]
        if not isinstance(operation_id, str) or UUID(operation_id).hex != operation_id.replace("-", ""):
            raise ValueError()
        digest = hashlib.sha256(
            json.dumps(parameters, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ExecutionError("maintenance_operation_invalid") from None
    service = VolumeMaintenance(volume, operation, client)
    journal = _directory(service.volume / "platform/maintenance")
    path = journal / (operation_id + "-" + action + ".json")
    lock_path = journal / "maintenance.lock"
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if path.is_symlink():
            raise ExecutionError("maintenance_journal_link_refused")
        if path.exists():
            previous = json.loads(path.read_text())
            if previous["parameters_digest"] != digest:
                raise ExecutionError("maintenance_plan_conflict")
            return previous["result"]
        if action == "backup":
            if parameters:
                raise ExecutionError("maintenance_parameters_invalid")
            result = service.backup()
        elif action == "migrate":
            if set(parameters) != {"plan", "snapshot"}:
                raise ExecutionError("maintenance_parameters_invalid")
            result = service.migrate_confirmed(parameters["plan"], snapshot=parameters["snapshot"])
        else:
            if set(parameters) != {"snapshot_id"}:
                raise ExecutionError("maintenance_parameters_invalid")
            result = service.restore_confirmed(parameters["snapshot_id"])
        temporary = journal / (".pending-" + uuid4().hex)
        try:
            with temporary.open("x") as stream:
                json.dump({"parameters_digest": digest, "result": result}, stream, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            _sync_directory(journal)
        finally:
            temporary.unlink(missing_ok=True)
        return result
    except BlockingIOError:
        raise ExecutionError("maintenance_writer_busy") from None
    finally:
        os.close(descriptor)


class KubernetesMaintenance:
    def __init__(self, runtime):
        self.runtime = runtime

    def _finish(self, operation, reference):
        from runtime_manager.executors.protocol import ExecutorError

        runtime = self.runtime
        runtime.request_stop(reference, operation)
        end = runtime.clock.time() + 60
        while True:
            runtime._controller()
            if runtime.confirm_stopped(reference)["stopped"] and runtime.cleanup(operation).get("complete"):
                return
            if runtime.clock.time() >= end:
                raise ExecutorError("maintenance_writer_stop_unconfirmed")
            runtime.clock.sleep(0.5)

    def request(self, operation, action, parameters):
        from dataclasses import replace
        from uuid import NAMESPACE_URL, uuid5

        from runtime_manager.executors.kubernetes import _seconds
        from runtime_manager.executors.protocol import ExecutorError
        from runtime_manager.k8s_templates import pod_template
        from runtime_manager.platform_client import PlatformError

        runtime = self.runtime
        current = runtime.platform.operation(operation["operation_id"])
        if (
            current["kind"] not in {"deploy", "migrate", "restore"}
            or current["status"] != "running"
            or action not in {"backup", "migrate", "restore"}
            or runtime.clock.time() >= _seconds(current["deadline"])
        ):
            raise ExecutorError("maintenance_operation_refused")
        body = current["payload"]
        if action == "migrate" and parameters.get("plan") != body.get("migration_plan"):
            raise ExecutorError("maintenance_plan_conflict")
        if action == "restore" and parameters != {"snapshot_id": body.get("snapshot_id")}:
            raise ExecutorError("maintenance_plan_conflict")
        digest = hashlib.sha256(json.dumps(parameters, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        progress = current.get("result", {}).get("maintenance_progress", {})
        previous = progress.get(action)
        if previous:
            if previous["parameters_digest"] != digest:
                raise ExecutorError("maintenance_plan_conflict")
            self._finish(current, previous["exec_ref"])
            return previous["result"]
        reference = str(uuid5(NAMESPACE_URL, "bisheng-maintenance:" + current["operation_id"] + ":" + action))
        purpose = "restore" if action == "restore" else "migrate"
        plan = runtime._plan(current, purpose, reference=reference, image=runtime.document["helper_image"])
        profile = (body.get("resolved_delivery") or {}).get("profile", {})
        document = {
            "operation": {
                "operation_id": current["operation_id"],
                "app_id": current["app_id"],
                "payload": {"resolved_delivery": {"profile": {k: profile.get(k, 10001) for k in ("uid", "gid")}}},
            },
            "action": action,
            "parameters": parameters,
        }
        plan = replace(
            plan,
            mode="image",
            command=(),
            app_secret="",
            secret_env=(),
            material_secret="material-" + reference.replace("-", ""),
            helper_env={"MATERIAL_PLAN": json.dumps(document, sort_keys=True, separators=(",", ":"))},
        )
        template = pod_template(plan)
        row = runtime._intent(current, plan, template, reference)
        runtime._volume(current, plan)
        grant = runtime._material(current, plan)
        pod = runtime._create(row, template)
        runtime.platform.bind_material_delegation(grant["delegation_id"], pod["metadata"]["uid"])
        while True:
            runtime.checkpoint()
            runtime._controller()
            latest = runtime.platform.operation(current["operation_id"])
            if (
                latest["status"] != "running"
                or latest.get("cancel_requested")
                or latest.get("payload", {}).get("cancel_requested")
            ):
                raise ExecutorError("maintenance_operation_cancelled")
            pod = runtime._fresh(runtime.platform.resource(reference))
            status = pod.get("status", {})
            if status.get("phase") == "Failed":
                raise ExecutorError("maintenance_phase_failed")
            if status.get("phase") == "Succeeded":
                output = runtime.client.logs(plan.name, container="maintenance", tail=100)
                lines = [
                    line.removeprefix("BISHENG_RUNTIME_RESULT ")
                    for line in output.splitlines()
                    if line.startswith("BISHENG_RUNTIME_RESULT ")
                ]
                try:
                    if len(lines) != 1 or len(lines[0]) > 65536:
                        raise ValueError()
                    result = json.loads(lines[0])
                    if not isinstance(result, dict) and not (action == "backup" and result is None):
                        raise ValueError()
                except (ValueError, TypeError):
                    raise ExecutorError("maintenance_result_invalid") from None
                break
            if runtime.clock.time() >= _seconds(current["deadline"]):
                raise ExecutorError("maintenance_phase_timeout")
            runtime.clock.sleep(0.5)
        latest = runtime.platform.operation(current["operation_id"])
        progress = dict(latest.get("result", {}).get("maintenance_progress", {}))
        progress[action] = {"exec_ref": reference, "parameters_digest": digest, "result": result}
        detail = {**latest.get("result", {}), "maintenance_progress": progress, "controller": runtime._controller()}
        try:
            runtime.platform.fact(
                latest, latest.get("fact_sequence", 0) + 1, latest["stage"], exec_ref=reference, detail=detail
            )
        except PlatformError:
            saved = (
                runtime.platform.operation(current["operation_id"]).get("result", {}).get("maintenance_progress", {})
            )
            if saved.get(action) != progress[action]:
                raise
        self._finish(current, reference)
        return result
