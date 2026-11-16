"""QA import capabilities and exact record binding before parser/write effects."""

import asyncio
from io import BytesIO
from types import SimpleNamespace

import pandas as pd

from bisheng.common.errcode.http_error import NotFoundError
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.knowledge.domain.models.knowledge_file import QAKnoweldgeDao
from bisheng.knowledge.domain.services.preview_source_service import PreviewSourceService


class QAImportService:
    MAX_IMPORT_BYTES = 20 * 1024 * 1024

    @staticmethod
    def bound_rows(ids: list[int], *, knowledge_id: int | None = None):
        """Reject missing/hidden/mixed-parent rows before any batch side effect."""
        if not ids or any(type(item) is not int or item <= 0 for item in ids):  # noqa: E721  # exact type, bool must not pass as int
            raise NotFoundError()
        expected = set(ids)
        rows = QAKnoweldgeDao.select_list(list(expected))
        tenant_id = get_current_tenant_id()
        if (
            tenant_id is None
            or {row.id for row in rows} != expected
            or len({row.knowledge_id for row in rows}) != 1
            or any(row.tenant_id != tenant_id for row in rows)
            or (knowledge_id is not None and any(row.knowledge_id != knowledge_id for row in rows))
        ):
            raise NotFoundError()
        return rows

    @classmethod
    async def source(cls, *, login_user, file_url: str, preview_upload_ref: str):
        """Resolve generic upload capability; never open caller URLs or paths."""
        if type(preview_upload_ref) is not str or not preview_upload_ref:  # noqa: E721  # exact type, bool must not pass as int
            raise NotFoundError()
        if get_current_tenant_id() != login_user.tenant_id:
            raise NotFoundError()
        # QA's existing upload UI stages through /knowledge/upload (scope zero).
        # Target QA knowledge permission is checked separately before this call.
        item = SimpleNamespace(preview_upload_ref=preview_upload_ref, preview_file_id=None, file_path=file_url)
        source = await PreviewSourceService.resolve(item=item, login_user=login_user, knowledge_id=0)
        if not source.file_name.lower().endswith((".xlsx", ".xls")):
            raise ValueError("QA import requires an uploaded Excel workbook")
        return source

    @classmethod
    async def dataframe(cls, source):
        storage = await get_minio_storage()
        # Server-controlled bucket/object identity comes only from resolved refs.
        response = await asyncio.to_thread(
            storage.download_object_sync, bucket_name=source.bucket, object_name=source.object_name
        )
        try:
            data = await asyncio.to_thread(response.read, cls.MAX_IMPORT_BYTES + 1)
        finally:
            response.close()
            response.release_conn()
        if not isinstance(data, bytes) or len(data) > cls.MAX_IMPORT_BYTES:
            raise ValueError("QA import workbook exceeds size limit")
        return await asyncio.to_thread(pd.read_excel, BytesIO(data))
