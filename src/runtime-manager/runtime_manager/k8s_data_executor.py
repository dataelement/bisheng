"""Bounded data transport to the same observed Pod; never a second online writer."""

from __future__ import annotations

import copy
import hashlib
import ipaddress
import json
import logging
import os
import shutil
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from tempfile import gettempdir, mkdtemp
from uuid import NAMESPACE_URL, uuid5

import httpx

from runtime_manager.errors import (
    DatabaseNotFoundError,
    DataBusyError,
    DataInvalidError,
    RowNotFoundError,
    TableNotFoundError,
)
from runtime_manager.executors.protocol import ExecutorError
from runtime_manager.k8s_client import KubernetesAPIError
from runtime_manager.k8s_templates import pod_template
from runtime_manager.platform_client import PlatformError

logger = logging.getLogger(__name__)


def _digest(parameters):
    return hashlib.sha256(
        json.dumps(parameters, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


class KubernetesDataExecutor:
    def __init__(self, runtime, *, transport=None):
        self.runtime = runtime
        self.cache_root = Path(gettempdir()) / "bisheng-data-exports"
        self.http = httpx.Client(transport=transport, trust_env=False, follow_redirects=False, timeout=2)

    def close(self):
        self.http.close()

    def _now(self):
        return self.runtime.clock.time()

    @staticmethod
    def _deadline(operation):
        value = datetime.fromisoformat(operation["deadline"].replace("Z", "+00:00"))
        return (value.replace(tzinfo=UTC) if value.tzinfo is None else value).timestamp()

    def _current(self, operation, *, active=True):
        current = self.runtime.platform.operation(operation["operation_id"])
        if (
            any(current.get(key) != operation.get(key) for key in ("app_id", "node_id", "generation", "owner_epoch"))
            or current.get("kind") != "data"
        ):
            raise DataBusyError("Data session scope mismatch")
        if active and (
            current["status"] in {"completed", "failed", "cancelled", "timed_out"}
            or self._now() >= self._deadline(current)
        ):
            raise DataBusyError("Data session is no longer active")
        return current

    def _pod(self, operation, target):
        row = self.runtime.platform.resource(target["exec_ref"])
        if (row["app_id"], row["node_id"], row["kind"], row.get("uid")) != (
            operation["app_id"],
            operation["node_id"],
            "Pod",
            target["pod_uid"],
        ) or row.get("stop_requested_at"):
            raise DataBusyError("Data execution identity is not confirmed")
        try:
            pod = self.runtime._fresh(row)
        except (KubernetesAPIError, ExecutorError):
            raise DataBusyError("Data execution observation is unavailable") from None
        try:
            address = ipaddress.ip_address(pod.get("status", {}).get("podIP", ""))
            ranges = self.runtime.document.get("pod_cidrs", [])
            if (
                not address.is_private
                or address.is_loopback
                or address.is_link_local
                or address.is_multicast
                or not any(address in ipaddress.ip_network(cidr) for cidr in ranges)
            ):
                raise ValueError()
        except (ValueError, TypeError):
            raise DataBusyError("Data execution address is outside the installed Pod network") from None
        host = f"[{address}]" if address.version == 6 else str(address)
        return row, pod, "http://" + host + ":8092"

    def _health(self, operation, target):
        _, _, base = self._pod(operation, target)
        remaining = self._deadline(operation) - self._now()
        if remaining <= 0:
            raise DataBusyError("Data session expired before helper readiness")
        try:
            response = self.http.get(base + "/healthz", timeout=min(2, remaining))
            response.raise_for_status()
            document = response.json()
            keys = document.get("key_ids")
            if (
                document.get("status") != "ok"
                or not isinstance(keys, list)
                or not 1 <= len(keys) <= 8
                or any(not isinstance(key, str) or not 1 <= len(key) <= 64 for key in keys)
            ):
                raise ValueError()
            return sorted(keys)
        except (httpx.HTTPError, ValueError):
            raise DataBusyError("Data helper is unavailable") from None

    def prepare_session(self, operation):
        current = self._current(operation)
        body = current["payload"]
        if body.get("online"):
            target = {"exec_ref": body["target_exec_ref"], "pod_uid": body["target_pod_uid"], "online": True}
            target["key_ids"] = self._health(current, target)
            return target
        # Only a volume already assigned by a prior lifecycle may be reused.
        volume_ref = str(uuid5(NAMESPACE_URL, "bisheng-volume:" + current["node_id"] + ":" + current["app_id"]))
        try:
            volume = self.runtime.platform.resource(volume_ref)
            if (
                volume["kind"] != "PersistentVolumeClaim"
                or volume["app_id"] != current["app_id"]
                or not volume.get("uid")
                or volume["cleanup_state"] == "complete"
            ):
                raise DataBusyError("Application data volume is not registered")
            self.runtime._fresh(volume)
        except (PlatformError, KubernetesAPIError, ExecutorError):
            raise DataBusyError("Application data volume is unavailable") from None
        # The backend additionally checks every production ledger row at intent creation.
        for old in self.runtime.platform.node_snapshot()["operations"]:
            if old["app_id"] != current["app_id"] or old["operation_id"] == current["operation_id"]:
                continue
            for row in self.runtime.platform.resources(old["operation_id"]):
                if (
                    row["kind"] == "Pod"
                    and row["purpose"] in {"serve", "data", "migrate", "restore"}
                    and row["stop_state"] != "confirmed"
                ):
                    raise DataBusyError("Previous application writer is not confirmed stopped")
        plan = self.runtime._plan(current, "data", deadline=min(60, int(self._deadline(current) - self._now())))
        plan = replace(plan, command=(), app_secret="", secret_env=(), material_secret="", mode="image")
        template = pod_template(plan)
        row = self.runtime._intent(current, plan, template, plan.resource_ref)
        pod = self.runtime._create(row, template)
        target = {"exec_ref": row["resource_ref"], "pod_uid": pod["metadata"]["uid"], "online": False}
        while True:
            self.runtime._controller()
            self._current(current)
            try:
                target["key_ids"] = self._health(current, target)
                return target
            except DataBusyError:
                if self._deadline(current) - self._now() <= 0.5:
                    raise
                self.runtime.clock.sleep(0.5)

    def request(self, operation, action, parameters):
        if operation["kind"] != "data":
            from runtime_manager.k8s_appdb import KubernetesMaintenance

            return KubernetesMaintenance(self.runtime).request(operation, action, parameters)
        if action == "prepare-session":
            return self.prepare_session(operation)
        if action == "finish-session":
            return self.cleanup_session(operation)
        current = self._current(operation)
        body = current["payload"]
        ticket = operation.get("data_grant")
        target = current.get("result", {}).get("data_target")
        try:
            claims = ticket["claims"]
            if (
                current.get("stage") != "ready"
                or action not in {"tables", "schema", "rows", "update", "export", "result"}
                or action != body["action"]
                or _digest(parameters) != body["parameters_digest"]
            ):
                raise ValueError()
            if (
                claims["operation_id"],
                claims["app_id"],
                claims["exec_ref"],
                claims["pod_uid"],
                claims["action"],
                claims["parameters_sha256"],
            ) != (
                current["operation_id"],
                current["app_id"],
                target["exec_ref"],
                target["pod_uid"],
                action,
                _digest(parameters),
            ):
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise DataBusyError("Owner data grant does not match the active session") from None
        _, _, base = self._pod(current, target)
        timeout = max(0.001, self._deadline(current) - self._now())
        document = {"grant": copy.deepcopy(ticket), "parameters": parameters}
        try:
            with self.http.stream("POST", base + "/actions", json=document, timeout=timeout) as response:
                if response.status_code >= 400:
                    raw = self._read_limited(response, 1024 * 1024)
                    try:
                        failure = json.loads(raw)
                    except ValueError:
                        failure = {}
                    error = failure.get("error", {})
                    error_type = {
                        "db_not_found": DatabaseNotFoundError,
                        "table_not_found": TableNotFoundError,
                        "row_not_found": RowNotFoundError,
                        "data_invalid": DataInvalidError,
                    }.get(error.get("code") if isinstance(error, dict) else None)
                    if error_type:
                        raise error_type("Application data operation failed")
                    reason = "data_result_unknown" if failure.get("state") == "unknown" else "data_helper_refused"
                    raise DataBusyError(
                        "Application data action is unavailable", reason=reason, request_id=body["request_id"]
                    )
                if action == "export":
                    return self._export(response, current)
                raw = self._read_limited(response, 16 * 1024**2)
                answer = json.loads(raw)
                if not isinstance(answer, dict):
                    raise ValueError()
                return answer
        except httpx.HTTPError:
            raise DataBusyError(
                "Data action result is unknown", reason="data_result_unknown", request_id=body["request_id"]
            ) from None
        except ValueError:
            raise DataBusyError(
                "Data helper result is invalid", reason="data_result_unknown", request_id=body["request_id"]
            ) from None

    @staticmethod
    def _read_limited(response, maximum):
        result = bytearray()
        for chunk in response.iter_bytes(64 * 1024):
            if len(result) + len(chunk) > maximum:
                raise DataBusyError("Data result exceeds the response limit", reason="data_result_unknown")
            result.extend(chunk)
        return bytes(result)

    def _export(self, response, operation):
        self.cache_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.cache_root.is_symlink() or self.cache_root.stat().st_uid != os.geteuid():
            raise DataBusyError("Data export cache is unavailable")
        temporary = Path(mkdtemp(prefix="export-", dir=self.cache_root))
        path = temporary / "export.csv"
        try:
            digest, size = hashlib.sha256(), 0
            with path.open("wb") as target:
                for chunk in response.iter_bytes(64 * 1024):
                    if self._now() >= self._deadline(operation):
                        raise DataBusyError("Data export deadline exceeded", reason="data_result_unknown")
                    target.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
            if response.headers.get("X-Content-Sha256") != digest.hexdigest() or response.headers.get(
                "Content-Length"
            ) != str(size):
                raise DataBusyError("Data export integrity mismatch", reason="data_result_unknown")
            # The existing FileResponse callback removes this short-lived cache.
            return path, temporary
        except BaseException:
            shutil.rmtree(temporary)
            raise

    def cleanup_exports(self):
        if not self.cache_root.exists() or self.cache_root.is_symlink():
            return
        cutoff = self._now() - self.runtime.config.cleanup_seconds
        for directory in self.cache_root.glob("export-*"):
            try:
                if directory.is_symlink() or not directory.is_dir():
                    continue
                metadata = directory.stat()
                if metadata.st_uid == os.geteuid() and metadata.st_mtime < cutoff:
                    shutil.rmtree(directory)
            except FileNotFoundError:
                # The FileResponse callback can win the cleanup race.
                continue
            except OSError as exc:
                # Cache expiry is independent of execution health and data safety.
                logger.warning("data export cache cleanup pending (%s)", type(exc).__name__)

    def cleanup_session(self, operation):
        current = self._current(operation, active=False)
        if not current["payload"].get("online"):
            return self.runtime.cleanup(current)
        target = current.get("result", {}).get("data_target") or {
            "exec_ref": current["payload"]["target_exec_ref"],
            "pod_uid": current["payload"]["target_pod_uid"],
        }
        row = self.runtime.platform.resource(target["exec_ref"])
        if row.get("uid") != target["pod_uid"]:
            return {"complete": False, "reason": "data_writer_identity_unknown"}
        if row["stop_state"] == "confirmed":
            return {"complete": True}
        if current["payload"].get("data_action_finished") not in {"done", "failed"} and self._now() < max(
            current["payload"].get("data_grant_not_after", 0),
            0 if current["payload"].get("data_grant_not_after") else self._deadline(current),
        ):
            return {"complete": False, "reason": "data_grant_acceptance_pending"}
        try:
            _, _, base = self._pod(current, target)
            response = self.http.get(base + "/execution-state", timeout=2)
            response.raise_for_status()
            if response.json() == {"idle": True}:
                return {"complete": True}
        except (httpx.HTTPError, DataBusyError, ValueError):
            return {"complete": False, "reason": "data_action_stop_unconfirmed"}
        return {"complete": False, "reason": "data_action_busy"}
