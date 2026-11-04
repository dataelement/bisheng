"""The manager's only platform-storage transport: scoped, signed, bounded streams."""

from __future__ import annotations

import hashlib
import os
import re
import ssl
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from runtime_manager.config import Config
from runtime_manager.platform_protocol import canonical_json, signed_headers

PREFIX = "/api/v1/internal/app-runtime/v2"
CHUNK_BYTES = 8 * 1024 * 1024


class PlatformError(RuntimeError):
    def __init__(self, reason, status=503):
        super().__init__(reason)
        self.status = status


class PlatformClient:
    def __init__(self, config: Config, *, transport=None, ca_file=None, timeout=60):
        self.config = config
        parsed = urlsplit(config.platform_base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            raise PlatformError("platform_base_url_invalid")
        ca_file = ca_file or config.platform_ca_file
        self._http = httpx.Client(
            base_url=config.platform_base_url.rstrip("/"),
            transport=transport,
            timeout=timeout,
            verify=ssl.create_default_context(cafile=str(ca_file) if ca_file else None),
            trust_env=False,
            follow_redirects=False,
        )

    def close(self):
        self._http.close()

    def _headers(self, method, path, raw=b"", extra=None):
        if not path.startswith(PREFIX + "/"):
            raise PlatformError("platform_path_refused")
        headers = signed_headers(
            method, path, raw, key_id=self.config.platform_key_id, secret=self.config.platform_secret
        )
        headers.update(extra or {})
        return headers

    @staticmethod
    def _check(response):
        if not 200 <= response.status_code < 300:
            reason = "platform_request_failed"
            try:
                error = response.json().get("error", {})
                if isinstance(error, dict):
                    reason = error.get("reason", reason)
            except (ValueError, AttributeError):
                reason = "platform_response_invalid"
            raise PlatformError(str(reason), response.status_code)

    def request(self, method, path, *, document=None, raw=None, extra=None):
        body = canonical_json(document) if document is not None else (raw or b"")
        headers = self._headers(method, path, body, extra)
        if document is not None:
            headers["Content-Type"] = "application/json"
        try:
            response = self._http.request(method, path, content=body, headers=headers)
        except httpx.HTTPError as exc:
            raise PlatformError("platform_unreachable") from exc
        self._check(response)
        try:
            return response.json()
        except ValueError as exc:
            raise PlatformError("platform_response_invalid") from exc

    @staticmethod
    def _resource_ref(value):
        try:
            if not isinstance(value, str) or str(UUID(value)) != value:
                raise ValueError()
        except (TypeError, ValueError, AttributeError):
            raise PlatformError("resource_reference_invalid", 400) from None
        return value

    def claim_controller(self, holder_id, expected_epoch):
        return self.request(
            "POST",
            PREFIX + "/controllers/claim",
            document={
                "holder_id": holder_id,
                "expected_epoch": expected_epoch,
            },
        )

    def renew_controller(self, holder_id, controller_epoch):
        return self.request(
            "POST",
            PREFIX + "/controllers/renew",
            document={
                "holder_id": holder_id,
                "controller_epoch": controller_epoch,
            },
        )

    def register_resource(self, document):
        return self.request("POST", PREFIX + "/resources", document=document)

    def observe_resource(self, resource_ref, document):
        reference = self._resource_ref(resource_ref)
        return self.request("POST", PREFIX + f"/resources/{reference}/observations", document=document)

    def create_material_delegation(self, document):
        # The document contains a public key only; workload keys never go to SQL.
        return self.request("POST", PREFIX + "/material-delegations", document=document)

    def bind_material_delegation(self, delegation_id, pod_uid):
        reference = self._resource_ref(delegation_id)
        self._resource_ref(pod_uid)
        return self.request("POST", PREFIX + f"/material-delegations/{reference}/bind", document={"pod_uid": pod_uid})

    def heartbeat(self, body):
        return self.request("POST", PREFIX + "/nodes/heartbeat", document=body)

    def node_snapshot(self):
        return self.request("GET", PREFIX + "/nodes/plan")

    def plan(self):
        return self.node_snapshot()["operations"]

    def resource(self, resource_ref):
        return self.request("GET", PREFIX + "/resources/" + self._resource_ref(resource_ref))

    def resources(self, operation_id):
        if not isinstance(operation_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,36}", operation_id):
            raise PlatformError("operation_reference_invalid", 400)
        return self.request("GET", PREFIX + "/resources?operation_id=" + operation_id)["resources"]

    def operation(self, operation_id):
        result = self.request("GET", PREFIX + "/operations/" + operation_id)
        if result.get("node_id") != self.config.node_id:
            raise PlatformError("operation_scope_refused")
        return result

    def claim(self, operation_id, *, command_nonce=None):
        return self.request(
            "POST", PREFIX + f"/operations/{operation_id}/claim", document={"command_nonce": command_nonce}
        )

    def nonce(self, key, ttl):
        result = self.request("POST", PREFIX + "/nonces", document={"key": key, "ttl": ttl})
        return bool(result["accepted"])

    def authorize_step(self, operation, phase, *, controller=None):
        return self.request(
            "POST",
            PREFIX + f"/operations/{operation['operation_id']}/authorize-step",
            document={
                "node_id": self.config.node_id,
                "generation": operation["generation"],
                "owner_epoch": operation["owner_epoch"],
                "phase": phase,
                "controller": controller or {},
            },
        )

    def fact(self, operation, sequence, phase, *, exec_ref="", detail=None):
        return self.request(
            "POST",
            PREFIX + f"/operations/{operation['operation_id']}/facts",
            document={
                "sequence": sequence,
                "node_id": self.config.node_id,
                "generation": operation["generation"],
                "owner_epoch": operation["owner_epoch"],
                "phase": phase,
                "exec_ref": exec_ref,
                "detail": detail or {},
            },
        )

    def download(self, operation_id, artifact_id, destination: Path, *, max_bytes=10 * 1024 * 1024 * 1024):
        session = self.request(
            "POST", PREFIX + "/downloads", document={"operation_id": operation_id, "artifact_id": artifact_id}
        )
        expected = int(session["size_bytes"])
        if expected < 0 or expected > max_bytes:
            raise PlatformError("artifact_size_limit")
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        path = PREFIX + f"/transfers/{session['transfer_id']}/content"
        headers = self._headers("GET", path, extra={"X-Runtime-Transfer": session["ticket"]})
        temporary = None
        try:
            with NamedTemporaryFile(prefix=".download-", dir=destination.parent, delete=False) as output:
                temporary = Path(output.name)
                digest = hashlib.sha256()
                size = 0
                with self._http.stream("GET", path, headers=headers) as response:
                    self._check(response)
                    for chunk in response.iter_bytes(1024 * 1024):
                        size += len(chunk)
                        if size > expected:
                            raise PlatformError("artifact_size_mismatch")
                        output.write(chunk)
                        digest.update(chunk)
                output.flush()
                os.fsync(output.fileno())
            if size != expected or digest.hexdigest() != session["sha256"]:
                raise PlatformError("artifact_digest_mismatch")
            os.replace(temporary, destination)
            return session
        except httpx.HTTPError as exc:
            raise PlatformError("platform_unreachable") from exc
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()

    def upload(self, operation_id, path: Path, *, kind, platform="", metadata=None):
        path = Path(path)
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
        session = self.request(
            "POST",
            PREFIX + "/transfers",
            document={
                "operation_id": operation_id,
                "kind": kind,
                "sha256": digest.hexdigest(),
                "size_bytes": size,
                "platform": platform,
                "metadata": metadata or {},
            },
        )
        ticket = {"X-Runtime-Transfer": session["ticket"]}
        prefix = PREFIX + f"/transfers/{session['transfer_id']}"
        offset = int(session["offset"])
        if not 0 <= offset <= size:
            raise PlatformError("transfer_offset_invalid")
        with path.open("rb") as source:
            source.seek(offset)
            while chunk := source.read(CHUNK_BYTES):
                try:
                    result = self.request("PUT", prefix + f"/content?offset={offset}", raw=chunk, extra=ticket)
                except PlatformError as exc:
                    if exc.status != 503:
                        raise
                    result = self.request("GET", prefix, extra=ticket)
                    if result["offset"] == offset:
                        result = self.request("PUT", prefix + f"/content?offset={offset}", raw=chunk, extra=ticket)
                if int(result["offset"]) != offset + len(chunk):
                    raise PlatformError("transfer_offset_invalid")
                offset += len(chunk)
        return self.request("POST", prefix + "/finalize", extra=ticket)

    def egress_policies(self):
        return self.request("GET", PREFIX + "/egress-policies")

    def dependencies(self, operation_id, input_key, *, artifact_id=None, verified=False):
        return self.request(
            "POST",
            PREFIX + "/dependency-plans",
            document={
                "operation_id": operation_id,
                "input_key": input_key,
                "artifact_id": artifact_id,
                "verified": verified,
            },
        )

    def egress(self, operation_id, phase, *, package_sources=()):
        return self.request(
            "POST",
            PREFIX + "/egress-bindings",
            document={"operation_id": operation_id, "phase": phase, "package_sources": list(package_sources)},
        )

    def application(self, app_id):
        return self.request("GET", PREFIX + "/apps/" + app_id + "/execution")

    def observation(self, document):
        return self.request("POST", PREFIX + "/observations", document=document)
