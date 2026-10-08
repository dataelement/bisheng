from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
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
from bisheng.knowledge.domain.services.knowledge_space_chat_service import KnowledgeSpaceChatService
from bisheng.knowledge.rag.async_retrieval_runtime import get_async_retrieval_runtime
from bisheng.open_endpoints.domain.services.filelib_retrieve_service import FilelibRetrieveService
from bisheng.open_endpoints.domain.services.filelib_retrieve_source_service import FilelibRetrieveSourceService


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
