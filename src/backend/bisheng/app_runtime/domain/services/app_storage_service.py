"""SDK-compatible attachment handles; only the platform accesses object storage."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from loguru import logger

from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeOperation, RuntimeRoute, RuntimeStorageBinding
from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeDeliveryRepository
from bisheng.app_runtime.domain.repositories.runtime_object_store import RuntimeObjectStore
from bisheng.core.context.tenant import bypass_tenant_filter


class AppStorageError(ValueError):
    def __init__(self, code, message, status=400, **detail):
        super().__init__(message)
        self.code = code
        self.status = status
        self.detail = detail


def validate_key(key):
    if (
        not key
        or not isinstance(key, str)
        or len(key.encode()) > 1024
        or "\\" in key
        or any(ord(x) < 32 or ord(x) == 127 for x in key)
        or any(x in {"", ".", ".."} for x in key.split("/"))
        or key.startswith("apps/")
    ):
        raise AppStorageError("invalid_object_key", "Invalid attachment path")
    return key


class AppStorageService:
    def __init__(self, repository=None, object_store=None, *, max_file_bytes=20 * 1024 * 1024):
        self.repo = repository or RuntimeDeliveryRepository()
        self.objects = object_store or RuntimeObjectStore()
        self.max_file_bytes = max_file_bytes

    async def issue(self, operation, *, base_url, preview_session=None):
        token = secrets.token_urlsafe(32)
        namespace = f"preview:{preview_session}" if preview_session else "production"
        prefix = f"tenants/{operation.tenant_id}/apps/{operation.app_id}/" + (
            f"previews/{preview_session}/attachments/" if preview_session else "attachments/"
        )
        if not preview_session:
            rows = await self.repo.find(RuntimeStorageBinding, app_id=operation.app_id, namespace="production")
            legacy = operation.payload.get("resolved_delivery", {}).get("legacy_storage_prefix")
            if rows:
                prefix = rows[-1].object_prefix
            elif legacy == f"apps/{operation.app_id}/attachments/":
                prefix = legacy
        binding = RuntimeStorageBinding(
            tenant_id=operation.tenant_id,
            app_id=operation.app_id,
            version_id=operation.version_id,
            operation_id=operation.id,
            namespace=namespace,
            object_prefix=prefix,
            credential_hash=hashlib.sha256(token.encode()).hexdigest(),
            state="active" if preview_session else "staged",
            expires_at=operation.deadline if preview_session else None,
        )
        await self.repo.save(binding)
        return {
            "binding_id": binding.id,
            "env": {
                "BISHENG_APP_STORAGE_ENDPOINT": base_url.rstrip("/") + f"/api/v1/apps/{operation.app_id}/storage",
                "BISHENG_APP_STORAGE_TOKEN": token,
                "BISHENG_APP_STORAGE_MAX_FILE_MB": str(self.max_file_bytes // (1024 * 1024)),
            },
        }

    async def authorize(self, app_id, token):
        if not token:
            raise AppStorageError("unauthorized", "Attachment handle refused", 401)
        with bypass_tenant_filter():
            rows = await self.repo.find(
                RuntimeStorageBinding, credential_hash=hashlib.sha256(token.encode()).hexdigest()
            )
            binding = rows[0] if rows else None
            if (
                binding is None
                or binding.app_id != app_id
                or binding.state != "active"
                or (binding.expires_at and binding.expires_at <= datetime.utcnow())
            ):
                raise AppStorageError("unauthorized", "Attachment handle refused", 401)
            if binding.namespace == "production":
                routes = await self.repo.find(RuntimeRoute, route_key=f"app:{app_id}")
                if (
                    not routes
                    or routes[0].status != "serving"
                    or routes[0].version_id != binding.version_id
                    or routes[0].operation_id != binding.operation_id
                ):
                    raise AppStorageError("unauthorized", "Attachment handle no longer active", 401)
            else:
                op = await self.repo.get(RuntimeOperation, binding.operation_id)
                if (
                    op is None
                    or op.payload.get("cancel_requested")
                    or op.status in {"completed", "failed", "cancelled", "timed_out"}
                ):
                    raise AppStorageError("unauthorized", "Preview handle expired", 401)
        return binding

    async def assert_live(self, binding):
        with bypass_tenant_filter():
            current = await self.repo.get(RuntimeStorageBinding, binding.id)
            if (
                current is None
                or current.state != "active"
                or (current.expires_at and current.expires_at <= datetime.utcnow())
            ):
                raise AppStorageError("unauthorized", "Attachment handle expired", 401)
            if current.namespace == "production":
                routes = await self.repo.find(RuntimeRoute, route_key=f"app:{binding.app_id}")
                if (
                    not routes
                    or routes[0].status != "serving"
                    or routes[0].version_id != binding.version_id
                    or routes[0].operation_id != binding.operation_id
                ):
                    raise AppStorageError("unauthorized", "Attachment handle no longer active", 401)

    @staticmethod
    def object_key(binding, key):
        value = binding.object_prefix + validate_key(key)
        if len(value.encode()) > 1024:
            raise AppStorageError("invalid_object_key", "Attachment path is too long")
        return value

    async def _store(self, method, *args, **kwargs):
        try:
            return await getattr(self.objects, method)(*args, **kwargs)
        except AppStorageError:
            raise
        except Exception as exc:
            logger.exception("app_runtime attachment object operation failed")
            raise AppStorageError("storage_unavailable", "Attachment storage unavailable", 503) from exc

    @staticmethod
    def public_meta(binding, row):
        if not row or not row.get("key", "").startswith(binding.object_prefix):
            raise AppStorageError("not_found", "Attachment not found", 404)
        return {**row, "key": row["key"][len(binding.object_prefix) :]}

    async def stat(self, binding, key):
        row = await self._store("stat", self.object_key(binding, key))
        return self.public_meta(binding, row)

    async def put(self, binding, key, stream, *, content_type="application/octet-stream", content_length=None):
        key = validate_key(key)
        if content_length is not None and content_length > self.max_file_bytes:
            raise AppStorageError(
                "payload_too_large", "Attachment size limit exceeded", 413, limit_bytes=self.max_file_bytes
            )
        with TemporaryDirectory(prefix="app-attachment-") as tmp:
            path = Path(tmp) / "file"
            size = 0
            with path.open("wb") as out:
                async for chunk in stream:
                    size += len(chunk)
                    if size > self.max_file_bytes:
                        raise AppStorageError(
                            "payload_too_large", "Attachment size limit exceeded", 413, limit_bytes=self.max_file_bytes
                        )
                    out.write(chunk)
            await self.assert_live(binding)
            await self._store("put", self.object_key(binding, key), path, content_type)
        return await self.stat(binding, key)

    async def get(self, binding, key):
        key = validate_key(key)
        try:
            async for chunk in self.objects.iter_content(self.object_key(binding, key)):
                yield chunk
        except Exception as exc:
            logger.exception("app_runtime attachment stream failed")
            raise AppStorageError("storage_unavailable", "Attachment storage unavailable", 503) from exc

    async def list(self, binding, *, prefix="", cursor=None, limit=100):
        if prefix:
            validate_key(prefix.rstrip("/"))
        if cursor:
            validate_key(cursor)
        limit = max(1, min(limit, 1000))
        rows = await self._store(
            "list",
            binding.object_prefix + prefix,
            start_after=binding.object_prefix + cursor if cursor else "",
            limit=limit + 1,
        )
        rows = [x for x in rows if x.get("key", "").startswith(binding.object_prefix)]
        objects = [self.public_meta(binding, x) for x in rows[:limit]]
        return {"objects": objects, "next_cursor": objects[-1]["key"] if len(rows) > limit and objects else None}

    async def delete(self, binding, key):
        await self.stat(binding, key)
        await self._store("delete", self.object_key(binding, key))

    async def revoke(self, app_id):
        for binding in await self.repo.find(RuntimeStorageBinding, app_id=app_id):
            binding.state = "revoked"
            await self.repo.save(binding)
