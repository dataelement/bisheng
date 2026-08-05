from __future__ import annotations

from loguru import logger
from starlette.requests import Request

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, KnowledgeFileStatus
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_repository_impl import (
    KnowledgeDocumentRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (
    KnowledgeDocumentVersionRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)
from bisheng.knowledge.domain.services.knowledge_version_service import KnowledgeVersionService
from bisheng.message.api.dependencies import get_message_service

FILELIB_SYNC_PENDING_VERSION_LINK_KEY = "filelib_sync_pending_version_link"


def build_filelib_sync_pending_version_link_metadata(
    *,
    target_document_id: int,
    replaced_file_id: int,
) -> dict:
    return {
        "target_document_id": int(target_document_id),
        "replaced_file_id": int(replaced_file_id),
    }


async def resolve_version_link_target_document_id(
    *,
    request: Request,
    login_user: UserPayload,
    existing_file: KnowledgeFile,
) -> int:
    """Resolve the document chain that a same-name overwrite should append to."""
    from bisheng.common.errcode.knowledge_space import VersionManagementDisabledError

    if int(existing_file.status) != KnowledgeFileStatus.SUCCESS.value:
        raise ValueError("existing same-name file is not parsed successfully")

    async with get_async_db_session() as session:
        service = KnowledgeVersionService(
            request=request,
            login_user=login_user,
            doc_repo=KnowledgeDocumentRepositoryImpl(session),
            version_repo=KnowledgeDocumentVersionRepositoryImpl(session),
            knowledge_file_repo=KnowledgeFileRepositoryImpl(session),
        )
        try:
            return await service.ensure_shougang_publish_document_for_file(int(existing_file.id))
        except VersionManagementDisabledError as exc:
            raise ValueError("version management is disabled") from exc


async def complete_pending_filelib_sync_version_link(file_id: int) -> bool:
    """Attach a parsed filelib-sync upload to its target document chain."""
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao

    db_file = KnowledgeFileDao.query_by_id_sync(file_id)
    if db_file is None or int(db_file.status) != KnowledgeFileStatus.SUCCESS.value:
        return False

    pending = (db_file.user_metadata or {}).get(FILELIB_SYNC_PENDING_VERSION_LINK_KEY)
    if not isinstance(pending, dict):
        return False

    target_document_id = pending.get("target_document_id")
    if target_document_id is None:
        return False

    login_user = UserPayload(
        user_id=int(db_file.user_id or 0),
        user_name=str(db_file.user_name or ""),
        tenant_id=int(db_file.tenant_id or 1),
    )
    runtime_request = Request(
        {
            "type": "http",
            "headers": [],
            "method": "POST",
            "path": "/filelib/file/sync",
        }
    )

    try:
        async with get_async_db_session() as session:
            service = KnowledgeVersionService(
                request=runtime_request,
                login_user=login_user,
                doc_repo=KnowledgeDocumentRepositoryImpl(session),
                version_repo=KnowledgeDocumentVersionRepositoryImpl(session),
                knowledge_file_repo=KnowledgeFileRepositoryImpl(session),
            )
            service.message_service = await get_message_service(session)
            await service.link_file_to_document(int(file_id), int(target_document_id))
            target_doc = await service.doc_repo.find_by_id(int(target_document_id))
            if target_doc is not None:
                target_doc.file_level_path = db_file.file_level_path
                target_doc.level = int(db_file.level or 0)
                await service.doc_repo.update(target_doc)
    except Exception as exc:
        logger.warning(
            "filelib sync version link failed file_id={} target_document_id={} error={}",
            file_id,
            target_document_id,
            exc,
        )
        return False

    metadata = dict(db_file.user_metadata or {})
    metadata.pop(FILELIB_SYNC_PENDING_VERSION_LINK_KEY, None)
    metadata["filelib_sync_version_linked"] = {
        "target_document_id": int(target_document_id),
        "replaced_file_id": pending.get("replaced_file_id"),
    }
    db_file.user_metadata = metadata
    KnowledgeFileDao.update(db_file)
    logger.info(
        "filelib sync version link completed file_id={} target_document_id={}",
        file_id,
        target_document_id,
    )
    return True
