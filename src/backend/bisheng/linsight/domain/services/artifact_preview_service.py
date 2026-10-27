"""Access check and PDF preview for task-mode result files (F111).

``load_accessible_version`` is the single access rule for a task result: the
session owner, an admin, or a share link to that session / version. Both the
download and the preview endpoints call it.

``get_pptx_preview`` converts a task-generated ``.ppt``/``.pptx`` to PDF on first
open and caches it in object storage, so every API node serves the same file.
A Redis lock keeps concurrent first opens to one conversion; a per-process
semaphore bounds how many LibreOffice runs one API process starts; a short-lived
failure marker stops a deck that cannot convert from being retried on every poll.
"""

from __future__ import annotations

import asyncio
import os
import posixpath
import tempfile
import time
import uuid

import fitz
from loguru import logger

from bisheng.common.errcode.http_error import NotFoundError, UnAuthorizedError
from bisheng.common.errcode.linsight import LinsightArtifactPreviewError
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.core.context.tenant import bypass_tenant_filter_if
from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.knowledge.rag.pipeline.loader.utils.libreoffice_converter import convert_ppt_to_pdf
from bisheng.linsight.domain.models.linsight_session_version import LinsightSessionVersion, LinsightSessionVersionDao

SLIDE_EXTS = (".ppt", ".pptx")
CONVERT_TIMEOUT_SECONDS = 120
LOCK_TTL_SECONDS = 180
# A deck LibreOffice cannot convert is not retried for this long, so polling
# clients and reopened tabs do not each start another full conversion run.
FAILURE_TTL_SECONDS = 300
_CONVERT_SLOTS = asyncio.Semaphore(2)
# Delete the lock only while it still holds our token: after a TTL expiry it may
# belong to another request.
_RELEASE_LOCK_LUA = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"


class LinsightArtifactPreviewService:
    @staticmethod
    async def load_accessible_version(session_version_id: str, login_user, share_link) -> LinsightSessionVersion:
        """Load a session version the caller may read, or raise NotFound / UnAuthorized."""
        with bypass_tenant_filter_if(share_link is not None):
            version = await LinsightSessionVersionDao.get_by_id(session_version_id)
        if not version:
            raise NotFoundError()
        if version.user_id == login_user.user_id or login_user.is_admin():
            return version
        # A workbench_chat share carries resource_id = the session and no versionId;
        # a version share carries meta_data.versionId. Either one grants read.
        shared_to_session = share_link is not None and share_link.resource_id == version.session_id
        shared_to_version = (
            share_link is not None
            and share_link.meta_data is not None
            and share_link.meta_data.get("versionId") == session_version_id
        )
        if not (shared_to_session or shared_to_version):
            raise UnAuthorizedError()
        return version

    @staticmethod
    def _owned_slide_key(version: LinsightSessionVersion, file_url: str, bucket: str) -> str:
        """Normalise ``file_url`` to an object key and require it to be this version's slide deck."""
        key = file_url.lstrip("/")
        if key.startswith(bucket + "/"):
            key = key[len(bucket) + 1 :]
        prefix = f"linsight/final_result/{version.id}/"
        parts = key.split("/")
        if (
            not key.startswith(prefix)
            or ".." in parts
            or "" in parts
            or posixpath.normpath(key) != key
            or not key.lower().endswith(SLIDE_EXTS)
        ):
            raise UnAuthorizedError()
        return key

    @classmethod
    async def get_pptx_preview(cls, version: LinsightSessionVersion, file_url: str) -> dict:
        """Return ``{"status": "ready", "file_path"}`` or ``{"status": "converting"}``."""
        minio = await get_minio_storage()
        key = cls._owned_slide_key(version, file_url, minio.bucket)
        file_id = os.path.splitext(posixpath.basename(key))[0]
        preview_key = f"linsight/preview/{version.id}/{file_id}.pdf"

        if await minio.object_exists(object_name=preview_key):
            return {"status": "ready", "file_path": await minio.get_share_link(preview_key)}

        redis = await get_redis_client()
        lock_key = f"linsight:pptx_preview:{version.id}:{file_id}"
        failed_key = f"linsight:pptx_preview_failed:{version.id}:{file_id}"
        await redis.acluster_nodes(lock_key)
        conn = redis.async_connection
        if await conn.get(failed_key):
            raise LinsightArtifactPreviewError()

        # Take a conversion slot before the lock, so the lock TTL only has to
        # cover the conversion itself and never a wait for a slot.
        async with _CONVERT_SLOTS:
            token = uuid.uuid4().hex
            if not await conn.set(lock_key, token, nx=True, ex=LOCK_TTL_SECONDS):
                return {"status": "converting"}
            try:
                # Another request may have finished while this one waited for a slot.
                if not await minio.object_exists(object_name=preview_key):
                    try:
                        pdf_bytes = await cls._convert(minio, key, version.id, file_id)
                    except LinsightArtifactPreviewError:
                        await conn.set(failed_key, b"1", ex=FAILURE_TTL_SECONDS)
                        raise
                    await minio.put_object(object_name=preview_key, file=pdf_bytes, content_type="application/pdf")
            finally:
                await conn.eval(_RELEASE_LOCK_LUA, 1, lock_key, token)
        return {"status": "ready", "file_path": await minio.get_share_link(preview_key)}

    @staticmethod
    async def _convert(minio, key: str, svid: str, file_id: str) -> bytes:
        source = await minio.get_object(object_name=key)
        if not source:
            logger.warning(f"pptx preview: source object missing svid={svid} file_id={file_id}")
            raise LinsightArtifactPreviewError()
        # File IO, LibreOffice and the page count all block: keep them off the event loop.
        return await asyncio.to_thread(_render_pdf, source, os.path.splitext(key)[1].lower(), svid, file_id)


def _render_pdf(source: bytes, ext: str, svid: str, file_id: str) -> bytes:
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="pptx_preview_") as tmp:
        input_path = os.path.join(tmp, f"{file_id}{ext}")
        with open(input_path, "wb") as fh:
            fh.write(source)
        # convert_ppt_to_pdf returns None/False on failure and only logs at debug level.
        output = convert_ppt_to_pdf(input_path, os.path.join(tmp, "out"), timeout=CONVERT_TIMEOUT_SECONDS)
        if not output or not os.path.exists(output):
            logger.warning(f"pptx preview: conversion failed svid={svid} file_id={file_id}")
            raise LinsightArtifactPreviewError()
        pages = _page_count(output)
        if pages <= 0:
            logger.warning(f"pptx preview: conversion produced no pages svid={svid} file_id={file_id}")
            raise LinsightArtifactPreviewError()
        with open(output, "rb") as fh:
            data = fh.read()
    logger.info(
        f"pptx preview: converted svid={svid} file_id={file_id} pages={pages} seconds={time.monotonic() - started:.1f}"
    )
    return data


def _page_count(path: str) -> int:
    try:
        with fitz.open(path) as doc:
            return doc.page_count
    except Exception as e:
        logger.warning(f"pptx preview: unreadable PDF {path}: {e}")
        return 0
