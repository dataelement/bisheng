"""Scope-checked content transfer; SQL confirmation is the persistence barrier."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeArtifact, RuntimeOperation, RuntimeTransfer
from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import (
    RuntimeConflict,
    RuntimeDeliveryRepository,
)
from bisheng.app_runtime.domain.repositories.runtime_object_store import RuntimeObjectStore
from bisheng.core.context.tenant import bypass_tenant_filter

KINDS = frozenset({"source", "dependencies", "compiled", "offline", "snapshot"})
CHUNK_LIMIT = 16 * 1024 * 1024


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _public_artifact(row):
    return {
        "artifact_id": row.id,
        "state": row.state,
        "sha256": row.sha256,
        "size_bytes": row.size_bytes,
        "confirmed_at": row.confirmed_at.isoformat() if row.confirmed_at else None,
        "platform": row.platform,
        "kind": row.kind,
    }


class RuntimeArtifactService:
    def __init__(
        self,
        repository=None,
        object_store=None,
        *,
        artifact_limit=2048 * 1024 * 1024,
        snapshot_limit=10240 * 1024 * 1024,
    ):
        self.repo = repository or RuntimeDeliveryRepository()
        self.objects = object_store or RuntimeObjectStore()
        self.artifact_limit = artifact_limit
        self.snapshot_limit = snapshot_limit

    async def operation(self, operation_id, node_id=None):
        op = await self.repo.get(RuntimeOperation, operation_id)
        if op is None or (node_id is not None and op.node_id != node_id):
            raise RuntimeConflict("operation_not_found")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", op.app_id) or op.tenant_id <= 0:
            raise RuntimeConflict("invalid_scope")
        if (
            op.payload.get("cancel_requested")
            or op.status in {"completed", "failed", "cancelled", "timed_out"}
            or op.deadline <= datetime.utcnow()
        ):
            raise RuntimeConflict("operation_expired")
        return op

    async def create_upload(self, operation_id, *, kind, sha256, size_bytes, platform="", metadata=None, node_id=None):
        op = await self.operation(operation_id, node_id)
        if kind not in KINDS or not re.fullmatch("[0-9a-f]{64}", sha256):
            raise RuntimeConflict("invalid_artifact")
        limit = self.snapshot_limit if kind == "snapshot" else self.artifact_limit
        if not isinstance(size_bytes, int) or size_bytes < 0 or size_bytes > limit:
            raise RuntimeConflict("artifact_size_limit")
        scope = f"{op.tenant_id}/{op.app_id}"
        async with self.repo.transaction():
            existing = await self.repo.find(RuntimeArtifact, scope_key=scope, kind=kind, sha256=sha256, lock=True)
            if existing:
                artifact = existing[0]
                if artifact.size_bytes != size_bytes or artifact.platform != platform:
                    raise RuntimeConflict("artifact_content_conflict")
            else:
                artifact = RuntimeArtifact(
                    tenant_id=op.tenant_id,
                    app_id=op.app_id,
                    scope_key=scope,
                    kind=kind,
                    sha256=sha256,
                    size_bytes=size_bytes,
                    platform=platform,
                    producer_operation_id=op.id,
                    metadata_=metadata or {},
                )
                artifact.object_key = f"tenants/{op.tenant_id}/apps/{op.app_id}/" + (
                    f"snapshots/{op.id}/{artifact.id}.sqlite"
                    if kind == "snapshot"
                    else f"artifacts/{kind}/{sha256}.tar.gz"
                )
                artifact = await self.repo.save(artifact)
            ticket = secrets.token_urlsafe(32)
            sessions = await self.repo.find(
                RuntimeTransfer, operation_id=op.id, artifact_id=artifact.id, action="upload", lock=True
            )
            transfer = (
                sessions[0]
                if sessions
                else RuntimeTransfer(
                    tenant_id=op.tenant_id,
                    app_id=op.app_id,
                    operation_id=op.id,
                    artifact_id=artifact.id,
                    node_id=op.node_id,
                    action="upload",
                    ticket_hash=_digest(ticket.encode()),
                    expires_at=op.deadline,
                )
            )
            transfer.ticket_hash = _digest(ticket.encode())
            if artifact.state == "verified":
                transfer.state = "confirmed"
                transfer.offset = artifact.size_bytes
            transfer = await self.repo.save(transfer)
        return {"transfer_id": transfer.id, "ticket": ticket, "offset": transfer.offset, **_public_artifact(artifact)}

    async def authorized_transfer(self, transfer_id, ticket, *, node_id=None, action="upload", lock=False):
        transfer = await self.repo.get(RuntimeTransfer, transfer_id, lock=lock)
        if transfer is None or not hmac.compare_digest(transfer.ticket_hash, _digest(ticket.encode())):
            raise RuntimeConflict("transfer_ticket_refused")
        if (
            transfer.action != action
            or (node_id is not None and node_id != transfer.node_id)
            or transfer.expires_at <= datetime.utcnow()
        ):
            raise RuntimeConflict("transfer_scope_expired")
        await self.operation(transfer.operation_id, node_id)
        with bypass_tenant_filter():
            artifact = await self.repo.get(RuntimeArtifact, transfer.artifact_id)
        if artifact is None or (
            (artifact.tenant_id, artifact.app_id) != (transfer.tenant_id, transfer.app_id)
            and not (transfer.action == "download" and artifact.visibility == "public" and artifact.kind == "offline")
        ):
            raise RuntimeConflict("artifact_not_found")
        return transfer, artifact

    async def append(self, transfer_id, ticket, offset, stream, *, node_id=None):
        transfer, artifact = await self.authorized_transfer(transfer_id, ticket, node_id=node_id)
        if offset < 0:
            raise RuntimeConflict("chunk_offset_conflict")
        with TemporaryDirectory(prefix="runtime-upload-") as tmp:
            path = Path(tmp) / "chunk"
            size = 0
            digest = hashlib.sha256()
            with path.open("wb") as output:
                async for chunk in stream:
                    size += len(chunk)
                    if size > CHUNK_LIMIT or offset + size > artifact.size_bytes:
                        raise RuntimeConflict("artifact_size_limit")
                    digest.update(chunk)
                    output.write(chunk)
            chunk_sha = digest.hexdigest()
            key = f"transfers/{transfer.id}/{offset}-{chunk_sha}"
            await self.objects.put(key, path)
            async with self.repo.transaction():
                transfer, artifact = await self.authorized_transfer(transfer_id, ticket, node_id=node_id, lock=True)
                parts = list(transfer.parts)
                if offset < transfer.offset:
                    match = [
                        x for x in parts if x["offset"] == offset and x["sha256"] == chunk_sha and x["size"] == size
                    ]
                    if not match:
                        raise RuntimeConflict("chunk_content_conflict")
                elif offset == transfer.offset and transfer.state == "open":
                    parts.append({"offset": offset, "size": size, "sha256": chunk_sha, "key": key})
                    transfer.parts = parts
                    transfer.offset += size
                    await self.repo.save(transfer)
                else:
                    raise RuntimeConflict("chunk_offset_conflict")
                return {"transfer_id": transfer.id, "offset": transfer.offset, "state": transfer.state}

    async def finalize(self, transfer_id, ticket, *, node_id=None):
        transfer, artifact = await self.authorized_transfer(transfer_id, ticket, node_id=node_id)
        if artifact.state == "verified":
            return _public_artifact(artifact)
        if transfer.offset != artifact.size_bytes:
            raise RuntimeConflict("transfer_incomplete")
        with TemporaryDirectory(prefix="runtime-finalize-") as tmp:
            path = Path(tmp) / "content"
            digest = hashlib.sha256()
            size = 0
            with path.open("wb") as output:
                for part in transfer.parts:
                    async for chunk in self.objects.iter_content(part["key"]):
                        size += len(chunk)
                        if size > artifact.size_bytes:
                            raise RuntimeConflict("artifact_size_limit")
                        digest.update(chunk)
                        output.write(chunk)
            if size != artifact.size_bytes or digest.hexdigest() != artifact.sha256:
                raise RuntimeConflict("artifact_digest_mismatch")
            await self.objects.put(artifact.object_key, path)
        async with self.repo.transaction():
            transfer, artifact = await self.authorized_transfer(transfer_id, ticket, node_id=node_id, lock=True)
            artifact.state = "verified"
            artifact.confirmed_at = datetime.utcnow()
            await self.repo.save(artifact)
            transfer.state = "confirmed"
            await self.repo.save(transfer)
        return _public_artifact(artifact)

    async def create_download(self, operation_id, artifact_id, *, node_id=None):
        op = await self.operation(operation_id, node_id)
        with bypass_tenant_filter():
            candidate = await self.repo.get(RuntimeArtifact, artifact_id)
        artifact = (
            candidate
            if candidate
            and (
                candidate.visibility == "public" or (candidate.tenant_id, candidate.app_id) == (op.tenant_id, op.app_id)
            )
            else None
        )
        public = bool(
            artifact
            and artifact.visibility == "public"
            and artifact.kind == "offline"
            and artifact.platform == (op.payload.get("profile") or {}).get("platform")
            and artifact.metadata_.get("profile_id") == (op.payload.get("profile") or {}).get("profile_id")
            and artifact.metadata_.get("profile_digest") == (op.payload.get("profile") or {}).get("profile_digest")
        )
        if (
            artifact is None
            or artifact.state != "verified"
            or ((artifact.tenant_id, artifact.app_id) != (op.tenant_id, op.app_id) and not public)
        ):
            raise RuntimeConflict("artifact_not_found")
        ticket = secrets.token_urlsafe(32)
        async with self.repo.transaction():
            existing = await self.repo.find(
                RuntimeTransfer, operation_id=op.id, artifact_id=artifact.id, action="download", lock=True
            )
            transfer = (
                existing[0]
                if existing
                else RuntimeTransfer(
                    tenant_id=op.tenant_id,
                    app_id=op.app_id,
                    operation_id=op.id,
                    artifact_id=artifact.id,
                    node_id=op.node_id,
                    action="download",
                    ticket_hash="",
                    expires_at=op.deadline,
                )
            )
            transfer.ticket_hash = _digest(ticket.encode())
            transfer.expires_at = min(op.deadline, datetime.utcnow() + timedelta(minutes=30))
            await self.repo.save(transfer)
        return {"transfer_id": transfer.id, "ticket": ticket, **_public_artifact(artifact)}

    async def content(self, transfer_id, ticket, *, node_id=None):
        _, artifact = await self.authorized_transfer(transfer_id, ticket, node_id=node_id, action="download")
        if artifact.state != "verified":
            raise RuntimeConflict("artifact_not_confirmed")
        async for chunk in self.objects.iter_content(artifact.object_key):
            yield chunk
