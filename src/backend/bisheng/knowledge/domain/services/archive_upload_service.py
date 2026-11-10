"""Temporary archive products share the tmp bucket's seven-day lifecycle."""
from __future__ import annotations

import asyncio
import json
import mimetypes
from pathlib import Path
import tempfile
import threading
from urllib.parse import unquote, urlparse
from uuid import uuid4

from loguru import logger

from bisheng.common.errcode.knowledge import KnowledgeArchiveUploadError
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.storage.minio.minio_manager import get_minio_storage, get_minio_storage_sync
from bisheng.knowledge.domain.services.archive_validation import ARCHIVE_EXTENSIONS, MAX_ARCHIVE_BYTES, MAX_ARCHIVE_FILES, ArchiveValidationError, expand_archive
from bisheng.knowledge.domain.upload_file_size import get_max_upload_bytes


class ArchiveUploadService:
    @classmethod
    async def upload(cls, file, user_id: int, accepts: str) -> dict:
        allowed = {s.strip().lower().lstrip(".") for s in accepts.split(",") if s.strip().startswith(".")}
        allowed &= ARCHIVE_EXTENSIONS
        if not allowed or not (file.filename or "").lower().endswith(".zip"):
            raise KnowledgeArchiveUploadError(reason="ZIP filename and allowed document/image types are required")
        max_bytes = get_max_upload_bytes("archive.zip")
        await file.seek(0)
        size = await asyncio.to_thread(cls._stream_size, file.file)
        if size > max_bytes:
            raise KnowledgeArchiveUploadError(reason="ZIP upload exceeds the configured file limit")
        tenant = get_current_tenant_id() or 1
        redis = await get_redis_client()
        lock_key = f"archive-upload-lock:{tenant}:{user_id}"
        token = uuid4().hex
        # Atomic NX+expiry; the legacy asetNx renews another request's lock.
        locked = await redis.async_connection.set(lock_key, token, nx=True, ex=120)
        if not locked:
            raise KnowledgeArchiveUploadError(reason="Another ZIP is being processed; retry after it finishes")
        archive_id = uuid4().hex
        prefix = f"archive-upload/{tenant}/{user_id}/{archive_id}"
        minio = None
        written = []
        stop = threading.Event()
        try:
            async with asyncio.timeout(75):
                minio = await get_minio_storage()
                bucket = minio.tmp_bucket
                with tempfile.TemporaryDirectory(prefix="bisheng-archive-") as temp:
                    worker = asyncio.create_task(asyncio.to_thread(expand_archive, file.file, Path(temp), allowed, max_bytes, stop))
                    try:
                        children, ignored = await asyncio.shield(worker)
                    except BaseException:
                        stop.set()
                        # Do not close the upload or delete temp paths while a thread uses them.
                        await asyncio.gather(worker, return_exceptions=True)
                        raise
                    rows = []
                    archive_name = Path((file.filename or "archive.zip").replace("\\", "/")).name
                    for child in children:
                        obj = f"{prefix}/{child.local_path.name}"
                        written.append(obj)
                        # Bytes use the cancellable async MinIO client, not fput's detached thread.
                        await minio.put_object(bucket_name=bucket, object_name=obj, file=child.local_path.read_bytes(),
                            content_type=mimetypes.guess_type(child.local_path.name)[0] or "application/octet-stream")
                        rows.append({"file_id": child.file_id, "file_name": Path(child.relative_path).name,
                            "relative_path": f"{archive_id}/{child.relative_path}", "source_path": child.relative_path,
                            "display_name": f"{archive_name}/{child.relative_path}", "size": child.size,
                            "object_name": obj, "archive_id": archive_id})
                    manifest = {"archive_id": archive_id, "archive_name": archive_name, "user_id": user_id,
                        "tenant_id": tenant, "files": rows, "ignored": ignored}
                    manifest_key = f"{prefix}/manifest.json"
                    written.append(manifest_key)
                    await minio.put_object(bucket_name=bucket, object_name=manifest_key,
                        file=json.dumps(manifest, ensure_ascii=False).encode(), content_type="application/json")
                    for row in rows:
                        row["file_path"] = await minio.get_share_link(row["object_name"], bucket=bucket)
                    return {"archive_id": archive_id, "archive_name": archive_name, "files": rows, "ignored": ignored}
        except BaseException as exc:
            stop.set()
            for obj in reversed(written):
                try:
                    await asyncio.shield(minio.remove_object(bucket_name=bucket, object_name=obj))
                except Exception:
                    logger.exception("archive rollback failed for {}; tmp-bucket lifecycle will reclaim it", obj)
            if isinstance(exc, (ArchiveValidationError, TimeoutError)):
                raise KnowledgeArchiveUploadError(reason=str(exc) or "ZIP processing timed out") from exc
            raise
        finally:
            try:
                await asyncio.shield(redis.async_connection.eval(
                    "if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('del',KEYS[1]) else return 0 end", 1, lock_key, token))
            except Exception:
                logger.exception("archive upload lock release failed; lock expires automatically")

    @staticmethod
    def _stream_size(stream) -> int:
        stream.seek(0, 2)
        size = stream.tell()
        stream.seek(0)
        return size

    @staticmethod
    def source_info(reference: str, user_id: int) -> dict | None:
        """Resolve only generated archive keys, never an arbitrary manifest URL."""
        import re
        path = unquote(urlparse(reference).path)
        match = re.search(r"(?:^|/)archive-upload/(\d+)/(\d+)/([0-9a-f]{32})/([0-9a-f]{32}\.[a-z0-9]+)$", path)
        if not match:
            return None
        tenant, owner, archive_id, name = match.groups()
        if int(tenant) != (get_current_tenant_id() or 1) or int(owner) != user_id:
            raise KnowledgeArchiveUploadError(reason="ZIP attachment does not belong to the current user")
        client = get_minio_storage_sync()
        prefix = f"archive-upload/{tenant}/{owner}/{archive_id}"
        raw = client.get_object_sync(bucket_name=client.tmp_bucket, object_name=f"{prefix}/manifest.json")
        manifest = json.loads(raw)
        row = next((row for row in manifest["files"] if row["object_name"] == f"{prefix}/{name}"), None)
        if row is None:
            raise KnowledgeArchiveUploadError(reason="ZIP attachment is missing from its manifest")
        return row

    @classmethod
    async def asource_info(cls, reference: str, user_id: int) -> dict | None:
        return await asyncio.to_thread(cls.source_info, reference, user_id)

    @classmethod
    def validate_references(cls, references: list[str], user_id: int) -> dict[str, dict]:
        """Server-side mixed-batch limits use manifest or downloaded byte sizes."""
        from bisheng.core.cache.utils import file_download

        sources = {}
        for reference in references:
            row = cls.source_info(reference, user_id)
            if row:
                sources[reference] = row
        if not sources:
            return sources
        if len(references) > MAX_ARCHIVE_FILES:
            raise KnowledgeArchiveUploadError(reason="An archive batch may contain at most 20 files, including loose files")
        size = 0
        for reference in references:
            row = sources.get(reference)
            size += row["size"] if row else Path(file_download(reference)[0]).stat().st_size
            if size > MAX_ARCHIVE_BYTES:
                raise KnowledgeArchiveUploadError(reason="Combined archive and loose files exceed 100 MiB")
        return sources
