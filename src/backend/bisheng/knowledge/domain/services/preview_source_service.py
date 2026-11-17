"""Resolve preview inputs to authorized server-controlled object storage keys."""

import secrets
from dataclasses import dataclass

from bisheng.common.errcode.http_error import NotFoundError
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFileDao, ParseType


@dataclass(frozen=True)
class PreviewSource:
    bucket: str
    object_name: str
    file_name: str
    cache_path: str
    share_url: str


class PreviewSourceService:
    @classmethod
    async def issue(cls, *, user_id: int, knowledge_id: int, object_name: str, file_path: str, file_name: str) -> str:
        tenant_id = get_current_tenant_id()
        if tenant_id is None:
            raise NotFoundError.http_exception()
        ref = secrets.token_urlsafe(32)
        redis = await get_redis_client()
        await redis.aset(
            f"knowledge_preview_upload:{ref}",
            {
                "user_id": user_id,
                "tenant_id": tenant_id,
                "knowledge_id": knowledge_id,
                "object_name": object_name,
                "file_path": file_path,
                "file_name": file_name,
            },
            expiration=86400,
        )
        return ref

    @classmethod
    async def resolve(cls, *, item, login_user, knowledge_id: int) -> PreviewSource:
        user_id = login_user.user_id
        tenant_id = get_current_tenant_id()
        if tenant_id is None or bool(item.preview_upload_ref) == bool(item.preview_file_id):
            raise NotFoundError.http_exception()
        minio = await get_minio_storage()
        if item.preview_upload_ref:
            redis = await get_redis_client()
            record = await redis.aget(f"knowledge_preview_upload:{item.preview_upload_ref}")
            if not isinstance(record, dict) or (
                record.get("user_id"),
                record.get("tenant_id"),
                record.get("knowledge_id"),
                record.get("file_path"),
            ) != (user_id, tenant_id, knowledge_id, item.file_path):
                raise NotFoundError.http_exception()
            return PreviewSource(
                minio.tmp_bucket, record["object_name"], record["file_name"], record["file_path"], record["file_path"]
            )
        file = await KnowledgeFileDao.query_by_id(item.preview_file_id)
        if (
            not file
            or file.knowledge_id != knowledge_id
            or file.tenant_id != tenant_id
            or file.file_type != FileType.FILE.value
            or not file.file_name
        ):
            raise NotFoundError.http_exception()
        from bisheng.permission.application.business_authorization import require_business_action

        await require_business_action(
            login_user, resource_type="knowledge_file", resource_id=file.id, action="download"
        )
        from bisheng.knowledge.domain.services.knowledge_utils import KnowledgeUtils

        cache_path = f"knowledge-preview-file:{file.id}:{item.preview_source}"
        if item.file_path != cache_path:
            raise NotFoundError.http_exception()
        if item.preview_source == "converted":
            if not file.preview_file_object_name and file.parse_type in {ParseType.LOCAL.value, ParseType.UNS.value}:
                object_name = str(file.id) if await minio.object_exists(minio.bucket, str(file.id)) else None
            else:
                object_name = KnowledgeUtils.resolve_preview_object_name(
                    file.id, file.file_name, file.preview_file_object_name
                )
            if not object_name:
                raise NotFoundError.http_exception()
            file_name = object_name.rsplit("/", 1)[-1]
        else:
            object_name = file.object_name or KnowledgeUtils.resolve_source_object_name(file.id, file.file_name)
            file_name = file.file_name
        return PreviewSource(
            minio.bucket, object_name, file_name, cache_path, await minio.get_share_link(object_name, minio.bucket)
        )
