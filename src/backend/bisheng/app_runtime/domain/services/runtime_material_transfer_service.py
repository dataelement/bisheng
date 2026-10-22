"""Workload-scoped resumable transfers; platform storage stays behind backend.

No operation-lifetime bypass is added to the legacy manager transfer endpoint.
Authority and each ticket are checked again after external I/O and before SQL.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets
import time
from datetime import UTC, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from bisheng.app_runtime.domain.models.runtime_delivery import (
    RuntimeArtifact,
    RuntimeAssignment,
    RuntimeOperation,
    RuntimeTransfer,
)
from bisheng.app_runtime.domain.models.runtime_kubernetes import RuntimeMaterialDelegation
from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict
from bisheng.app_runtime.domain.services import runtime_material_protocol as wire
from bisheng.app_runtime.domain.services.runtime_artifact_service import RuntimeArtifactService, _public_artifact
from bisheng.core.context.tenant import bypass_tenant_filter, tenant_execution_scope

_METADATA = {
    "compiled": {"source_artifact_id", "dependency_artifact_id"},
    "dependencies": {"input_key", "profile_id", "profile_digest"},
    "snapshot": {"format", "integrity_result"},
}


def _reject(reason, status=409):
    raise wire.MaterialProtocolError(reason, status)


def _stamp(value):
    return int(value.replace(tzinfo=UTC).timestamp())


class RuntimeMaterialTransferService:
    def __init__(self, authority, object_store=None, *, artifact_limit=2048 * 1024**2, snapshot_limit=10240 * 1024**2):
        self.authority = authority
        self.repo = authority.repo
        self.artifacts = RuntimeArtifactService(
            self.repo, object_store, artifact_limit=artifact_limit, snapshot_limit=snapshot_limit
        )
        self.objects = self.artifacts.objects

    async def _current(self, scope):
        return await self.authority.revalidate(scope)

    async def _lock_authority(self, scope):
        # Keep the operation/assignment order used by the control repository.
        await self.repo.get(RuntimeOperation, scope.operation.id, lock=True)
        await self.repo.find(RuntimeAssignment, app_id=scope.operation.app_id, lock=True)
        await self.repo.get(RuntimeMaterialDelegation, scope.delegation.id, lock=True)
        return await self._current(scope)

    def _metadata(self, scope, request):
        metadata = request.get("metadata", {})
        if (
            not isinstance(metadata, dict)
            or set(metadata) - _METADATA.get(request["kind"], set())
            or any(not isinstance(value, str) or len(value) > 512 for value in metadata.values())
        ):
            _reject("material_metadata_refused", 400)
        payload = scope.operation.payload
        frozen = payload.get("resolved_delivery") or {}
        for name in ("source_artifact_id", "dependency_artifact_id"):
            if name in metadata and metadata[name] != (payload.get(name) or frozen.get(name)):
                _reject("material_metadata_scope_refused", 403)
        profile = frozen.get("profile") or payload.get("profile") or {}
        for name in ("profile_id", "profile_digest"):
            if name in metadata and metadata[name] != profile.get(name):
                _reject("material_metadata_scope_refused", 403)
        return metadata

    def _document(self, transfer, artifact, *, ticket=None):
        result = {
            **_public_artifact(artifact),
            "transfer_id": transfer.id,
            "action": transfer.action,
            "state": transfer.state,
            "offset": transfer.offset,
            "expires_at": _stamp(transfer.expires_at),
        }
        if ticket is not None:
            result["ticket"] = ticket
        return result

    async def exchange(self, scope):
        request = scope.request
        try:
            with tenant_execution_scope(scope.delegation.tenant_id):
                async with self.repo.transaction():
                    current = await self._lock_authority(scope)
                    action = request["action"]
                    if action == "upload":
                        if "upload:" + request["kind"] not in current.delegation.allowed_actions:
                            _reject("material_upload_refused", 403)
                        metadata = self._metadata(current, request)
                        artifact = await self.artifacts._upload_artifact(
                            current.operation,
                            kind=request["kind"],
                            sha256=request["sha256"],
                            size_bytes=request["size_bytes"],
                            platform=request.get("platform", ""),
                            metadata=metadata,
                        )
                        declarations = current.delegation.upload_declarations or {}
                        declaration = {
                            "kind": request["kind"],
                            "sha256": request["sha256"],
                            "size_bytes": request["size_bytes"],
                            "platform": request.get("platform", ""),
                            "metadata": metadata,
                        }
                        if artifact.id in declarations and declarations[artifact.id] != declaration:
                            _reject("material_upload_declaration_conflict")
                        if artifact.id not in declarations:
                            current.delegation.upload_declarations = {**declarations, artifact.id: declaration}
                            await self.repo.save(current.delegation)
                    else:
                        if request["artifact_id"] not in current.delegation.allowed_artifacts:
                            _reject("material_artifact_refused", 403)
                        with bypass_tenant_filter():
                            artifact = await self.repo.get(RuntimeArtifact, request["artifact_id"])
                        if artifact is None or artifact.state != "verified":
                            _reject("material_artifact_refused", 403)
                    records = await self.repo.find(
                        RuntimeTransfer,
                        authorization_kind=current.delegation.scope_kind,
                        authorization_id=current.delegation.id,
                        artifact_id=artifact.id,
                        action=action,
                        lock=True,
                    )
                    expires = self.authority.clock() + timedelta(seconds=300)
                    if current.deadline is not None:
                        expires = min(expires, current.deadline)
                    transfer = (
                        records[0]
                        if records
                        else RuntimeTransfer(
                            id=str(uuid4()),
                            tenant_id=current.delegation.tenant_id,
                            app_id=current.delegation.app_id,
                            operation_id=current.operation.id,
                            authorization_kind=current.delegation.scope_kind,
                            authorization_id=current.delegation.id,
                            artifact_id=artifact.id,
                            node_id=current.delegation.node_id,
                            action=action,
                            ticket_hash="",
                            expires_at=expires,
                        )
                    )
                    ticket = secrets.token_urlsafe(32)
                    transfer.ticket_hash = hashlib.sha256(ticket.encode()).hexdigest()
                    transfer.expires_at = expires
                    if action == "upload" and artifact.state == "verified":
                        transfer.state, transfer.offset = "confirmed", artifact.size_bytes
                    await self.repo.save(transfer)
                    return self._document(transfer, artifact, ticket=ticket)
        except RuntimeConflict as exc:
            _reject(str(exc))
        except IntegrityError:
            # Retry the signed exchange with a fresh nonce; the SQL winner is reused.
            _reject("material_exchange_claim_conflict")

    async def _record(self, scope, ticket, transfer_id, *, lock=False):
        current = await (self._lock_authority(scope) if lock else self._current(scope))
        transfer = await self.repo.get(RuntimeTransfer, transfer_id, lock=lock)
        if transfer is None or not hmac.compare_digest(
            transfer.ticket_hash, hashlib.sha256(ticket.encode()).hexdigest()
        ):
            _reject("material_ticket_refused", 401)
        if transfer.expires_at <= self.authority.clock():
            _reject("material_ticket_expired", 401)
        if (
            transfer.authorization_kind,
            transfer.authorization_id,
            transfer.tenant_id,
            transfer.app_id,
            transfer.operation_id,
            transfer.node_id,
        ) != (
            current.delegation.scope_kind,
            current.delegation.id,
            current.delegation.tenant_id,
            current.delegation.app_id,
            current.operation.id,
            current.delegation.node_id,
        ):
            _reject("material_transfer_scope_refused", 403)
        with bypass_tenant_filter():
            artifact = await self.repo.get(RuntimeArtifact, transfer.artifact_id)
        if artifact is None:
            _reject("material_artifact_refused", 403)
        if transfer.action == "download":
            if (
                "download" not in current.delegation.allowed_actions
                or artifact.id not in current.delegation.allowed_artifacts
                or artifact.state != "verified"
            ):
                _reject("material_artifact_refused", 403)
        elif transfer.action == "upload":
            if "upload:" + artifact.kind not in current.delegation.allowed_actions or (
                artifact.tenant_id,
                artifact.app_id,
            ) != (transfer.tenant_id, transfer.app_id):
                _reject("material_upload_refused", 403)
        else:
            _reject("material_action_invalid", 403)
        return transfer, artifact

    async def authorize(self, proof, scope, method, target, body):
        transfer_id = target.split("/transfers/", 1)[1].split("/", 1)[0].split("?", 1)[0]
        with tenant_execution_scope(scope.delegation.tenant_id):
            transfer, artifact = await self._record(scope, proof.ticket, transfer_id)
        path = target.partition("?")[0]
        action = (
            "download"
            if method == "GET" and path.endswith("/content")
            else ("upload" if method == "PUT" or path.endswith("/finalize") else transfer.action)
        )
        if transfer.action != action:
            _reject("material_ticket_action_refused", 403)
        if path.endswith("/finalize"):
            declaration = wire.parse_control(body, allowed={"sha256", "size_bytes"}, required={"sha256", "size_bytes"})
            if (
                declaration != {"sha256": artifact.sha256, "size_bytes": artifact.size_bytes}
                or type(declaration["size_bytes"]) is not int
            ):
                _reject("material_finalize_declaration_conflict")

    async def status(self, scope, ticket, transfer_id):
        with tenant_execution_scope(scope.delegation.tenant_id):
            transfer, artifact = await self._record(scope, ticket, transfer_id)
            return self._document(transfer, artifact)

    async def _io(self, scope, ticket, transfer_id, awaitable, *, end=None):
        """Bound I/O, check revocation while waiting, and propagate cancellation."""
        task = None
        try:
            while True:
                with tenant_execution_scope(scope.delegation.tenant_id):
                    transfer, _ = await self._record(scope, ticket, transfer_id)
                    if task is None:
                        task = asyncio.ensure_future(awaitable)
                remaining = (transfer.expires_at - self.authority.clock()).total_seconds()
                if end is not None:
                    remaining = min(remaining, end - time.monotonic())
                if remaining <= 0:
                    _reject("material_request_expired", 401)
                done, _ = await asyncio.wait({task}, timeout=min(5, remaining))
                if done:
                    result = task.result()
                    with tenant_execution_scope(scope.delegation.tenant_id):
                        await self._record(scope, ticket, transfer_id)
                    return result
        finally:
            if task is None:
                # Authorization failed before the I/O coroutine was scheduled.
                awaitable.close()
            elif not task.done():
                task.cancel()
                results = await asyncio.gather(task, return_exceptions=True)
                for result in results:
                    if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
                        raise result

    async def append(self, scope, ticket, transfer_id, offset, body):
        wire.unsigned_integer(offset)
        if not body or len(body) > wire.CHUNK_LIMIT:
            _reject("material_chunk_limit", 413)
        with tenant_execution_scope(scope.delegation.tenant_id):
            transfer, artifact = await self._record(scope, ticket, transfer_id)
        if transfer.action != "upload":
            _reject("material_ticket_action_refused", 403)
        if offset + len(body) > artifact.size_bytes:
            _reject("material_size_limit", 413)
        digest = hashlib.sha256(body).hexdigest()
        key = f"transfers/{transfer_id}/{offset}-{digest}"
        with TemporaryDirectory(prefix="material-upload-") as directory:
            path = Path(directory) / "chunk"
            path.write_bytes(body)
            await self._io(scope, ticket, transfer_id, self.objects.put(key, path), end=time.monotonic() + 60)
        with tenant_execution_scope(scope.delegation.tenant_id):
            async with self.repo.transaction():
                transfer, artifact = await self._record(scope, ticket, transfer_id, lock=True)
                part = {"offset": offset, "size": len(body), "sha256": digest, "key": key}
                if offset < transfer.offset:
                    if part not in transfer.parts:
                        _reject("material_chunk_content_conflict")
                elif offset == transfer.offset and transfer.state == "open":
                    transfer.parts = [*transfer.parts, part]
                    transfer.offset += len(body)
                    await self.repo.save(transfer)
                else:
                    _reject("material_chunk_offset_conflict")
                return {"transfer_id": transfer.id, "offset": transfer.offset, "state": transfer.state}

    async def content(self, scope, ticket, transfer_id, offset, length):
        wire.unsigned_integer(offset)
        wire.unsigned_integer(length, maximum=wire.CHUNK_LIMIT)
        if length == 0:
            _reject("material_chunk_length_invalid", 400)
        with tenant_execution_scope(scope.delegation.tenant_id):
            transfer, artifact = await self._record(scope, ticket, transfer_id)
        if transfer.action != "download":
            _reject("material_ticket_action_refused", 403)
        if offset > artifact.size_bytes or (artifact.size_bytes and offset == artifact.size_bytes):
            _reject("material_range_unsatisfied", 416)
        size = min(length, artifact.size_bytes - offset)
        headers = {"Content-Length": str(size)}
        if size:
            headers["Content-Range"] = f"bytes {offset}-{offset + size - 1}/{artifact.size_bytes}"

        async def stream():
            if not size:
                return
            source = self.objects.iter_content(artifact.object_key)
            position, emitted, end = 0, 0, time.monotonic() + 60
            try:
                while emitted < size:
                    try:
                        chunk = await self._io(scope, ticket, transfer_id, anext(source), end=end)
                    except StopAsyncIteration:
                        _reject("material_object_truncated", 503)
                    start = max(0, offset - position)
                    part = chunk[start : start + size - emitted]
                    position += len(chunk)
                    if part:
                        emitted += len(part)
                        yield part
            finally:
                await source.aclose()

        return (206 if size else 200), headers, stream()

    async def finalize(self, scope, ticket, transfer_id, declaration):
        with tenant_execution_scope(scope.delegation.tenant_id):
            transfer, artifact = await self._record(scope, ticket, transfer_id)
        if transfer.action != "upload":
            _reject("material_ticket_action_refused", 403)
        if (
            declaration != {"sha256": artifact.sha256, "size_bytes": artifact.size_bytes}
            or type(declaration.get("size_bytes")) is not int
        ):
            _reject("material_finalize_declaration_conflict")
        if artifact.state == "verified":
            return _public_artifact(artifact)
        if transfer.offset != artifact.size_bytes:
            _reject("material_transfer_incomplete")
        with TemporaryDirectory(prefix="material-finalize-") as directory:
            path = Path(directory) / "content"
            digest, size = hashlib.sha256(), 0
            with path.open("wb") as output:
                for part in transfer.parts:
                    if part["offset"] != size:
                        _reject("material_chunk_offset_conflict")
                    source = self.objects.iter_content(part["key"])
                    part_digest, part_size = hashlib.sha256(), 0
                    try:
                        while True:
                            try:
                                chunk = await self._io(scope, ticket, transfer_id, anext(source))
                            except StopAsyncIteration:
                                break
                            size += len(chunk)
                            part_size += len(chunk)
                            if size > artifact.size_bytes:
                                _reject("material_size_limit", 413)
                            part_digest.update(chunk)
                            digest.update(chunk)
                            output.write(chunk)
                    finally:
                        await source.aclose()
                    if part_size != part["size"] or part_digest.hexdigest() != part["sha256"]:
                        _reject("material_chunk_digest_mismatch")
            if size != artifact.size_bytes or digest.hexdigest() != artifact.sha256:
                _reject("material_artifact_digest_mismatch")
            await self._io(scope, ticket, transfer_id, self.objects.put(artifact.object_key, path))
        with tenant_execution_scope(scope.delegation.tenant_id):
            async with self.repo.transaction():
                transfer, artifact = await self._record(scope, ticket, transfer_id, lock=True)
                artifact.state, artifact.confirmed_at = "verified", self.authority.clock()
                transfer.state = "confirmed"
                await self.repo.save(artifact)
                await self.repo.save(transfer)
                return _public_artifact(artifact)
