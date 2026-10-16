from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.services.config_service import settings
from bisheng.core.database import get_async_db_session
from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_repository_impl import (
    KnowledgeDocumentRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (
    KnowledgeDocumentVersionRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_mcp_repository_impl import (
    KnowledgeMcpRepositoryImpl,
)
from bisheng.knowledge.domain.services.knowledge_document_entry_resolver import KnowledgeDocumentEntryResolver
from bisheng.knowledge.domain.services.knowledge_mcp_content_service import KnowledgeMcpContentService
from bisheng.knowledge.domain.services.knowledge_mcp_ingestion_service import KnowledgeMcpIngestionService
from bisheng.knowledge.domain.services.knowledge_mcp_query_service import KnowledgeMcpQueryService
from bisheng.knowledge.domain.services.knowledge_space_chat_service import KnowledgeSpaceChatService
from bisheng.knowledge.rag.async_retrieval_runtime import get_async_retrieval_runtime
from bisheng.mcp_server.domain.schemas.ingestion import MAX_FILE_BYTES, MAX_TEXT_BYTES
from bisheng.open_endpoints.domain.schemas.filelib import RetrieveReq, RetrieveResp
from bisheng.open_endpoints.domain.services.filelib_retrieve_service import FilelibRetrieveService
from bisheng.open_endpoints.domain.services.filelib_retrieve_source_service import FilelibRetrieveSourceService
from bisheng.open_endpoints.domain.services.filelib_sync_factory import build_knowledge_space_service_for_filelib_sync


async def get_source_origin() -> str | None:
    config = await settings.aget_all_config()
    return (config.get("shougang") or {}).get("portal_base_url")


@asynccontextmanager
async def build_search_service(request: Any, user: UserPayload) -> AsyncIterator[FilelibRetrieveService]:
    runtime = await get_async_retrieval_runtime()
    async with get_async_db_session() as session:
        file_repo = KnowledgeFileRepositoryImpl(session)
        version_repo = KnowledgeDocumentVersionRepositoryImpl(session)
        doc_repo = KnowledgeDocumentRepositoryImpl(session)
        chat = KnowledgeSpaceChatService(request=request, login_user=user)
        chat.version_repo = version_repo
        chat.doc_repo = doc_repo
        chat.file_repo = file_repo
        chat.retrieval_runtime = runtime
        source = FilelibRetrieveSourceService(
            file_repository=file_repo,
            version_repository=version_repo,
            storage=await get_minio_storage(),
            max_concurrency=runtime.config.max_source_link_concurrency,
            public_origin_provider=get_source_origin,
        )
        yield FilelibRetrieveService(chat, source, runtime)


@asynccontextmanager
async def build_tool_services(
    request: Any, user: UserPayload, *, search_factory: Callable[..., Any] = build_search_service
) -> AsyncIterator[Any]:
    async with get_async_db_session() as session:
        owner = build_knowledge_space_service_for_filelib_sync(session=session, login_user=user, request=request)
        repository = KnowledgeMcpRepositoryImpl(session)
        query = KnowledgeMcpQueryService(repository, owner)

        async def permissions(file_id: int, space_id: int) -> set[str]:
            return await query.permissions("knowledge_file", file_id, space_id)

        resolver = KnowledgeDocumentEntryResolver(
            document_repository=owner.doc_repo,
            version_repository=owner.version_repo,
            file_repository=owner.knowledge_file_repo,
            permission_loader=permissions,
        )
        owner.document_entry_resolver = resolver
        storage = await get_minio_storage()
        content = KnowledgeMcpContentService(repository, query, storage, resolver)
        ingestion = KnowledgeMcpIngestionService(
            query, storage, max_file_bytes=MAX_FILE_BYTES, max_text_bytes=MAX_TEXT_BYTES
        )

        async def retrieve_chunks(*, knowledge_base_ids: list[int], **params: Any) -> RetrieveResp:
            for knowledge_id in dict.fromkeys(knowledge_base_ids):
                await query.require_space(knowledge_id)
            async with search_factory(request, user) as service:
                return await service.retrieve(RetrieveReq(knowledge_base_ids=knowledge_base_ids, **params))

        yield SimpleNamespace(
            list_knowledge=query.list_knowledge,
            list_folders=query.list_folders,
            list_files=query.list_files,
            search_files=query.search_files,
            get_file_detail=content.get_file_detail,
            get_file_source=content.get_file_source,
            create_document=ingestion.create_document,
            upload_file=ingestion.upload_file,
            retrieve_chunks=retrieve_chunks,
        )
