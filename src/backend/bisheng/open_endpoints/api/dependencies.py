from typing import TYPE_CHECKING

from fastapi import Depends, Request
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.dependencies.core_deps import get_db_session
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.developer_token.api.dependencies import get_developer_token_user
from bisheng.knowledge.api.dependencies import get_knowledge_document_version_repository
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_repository_impl import KnowledgeRepositoryImpl
from bisheng.knowledge.domain.repositories.interfaces.knowledge_document_version_repository import (
    KnowledgeDocumentVersionRepository,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_file_repository import KnowledgeFileRepository
from bisheng.knowledge.domain.repositories.interfaces.knowledge_repository import KnowledgeRepository
from bisheng.knowledge.domain.services.knowledge_file_service import KnowledgeFileService
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService

if TYPE_CHECKING:
    from bisheng.knowledge.domain.services.knowledge_space_chat_service import KnowledgeSpaceChatService


async def get_knowledge_repository(
        session: AsyncSession = Depends(get_db_session),
) -> KnowledgeRepository:
    """Dapatkan KnowledgeRepositoryInstance Dependencies"""
    return KnowledgeRepositoryImpl(session)


async def get_knowledge_file_repository(
        session: AsyncSession = Depends(get_db_session),
) -> 'KnowledgeFileRepository':
    """Dapatkan KnowledgeFileRepositoryInstance Dependencies"""

    return KnowledgeFileRepositoryImpl(session)


async def get_knowledge_service(
        knowledge_repository: KnowledgeRepository = Depends(get_knowledge_repository),
        knowledge_file_repository: KnowledgeFileRepository = Depends(get_knowledge_file_repository),
) -> 'KnowledgeService':
    """Dapatkan KnowledgeServiceInstance Dependencies"""
    return KnowledgeService(knowledge_repository=knowledge_repository,
                            knowledge_file_repository=knowledge_file_repository)


async def get_knowledge_file_service(
        knowledge_repository: KnowledgeRepository = Depends(get_knowledge_repository),
        knowledge_file_repository: KnowledgeFileRepository = Depends(get_knowledge_file_repository),
) -> 'KnowledgeFileService':
    """Dapatkan KnowledgeFileServiceInstance Dependencies"""
    return KnowledgeFileService(
        knowledge_repository=knowledge_repository,
        knowledge_file_repository=knowledge_file_repository,
    )


async def get_knowledge_space_chat_service_for_openapi(
        request: Request,
        developer_user: UserPayload = Depends(get_developer_token_user),
        version_repo: KnowledgeDocumentVersionRepository = Depends(
            get_knowledge_document_version_repository
        ),
) -> 'KnowledgeSpaceChatService':
    """KnowledgeSpaceChatService bound to the authenticated developer-token user.

    Used by the OpenAPI surface so external systems authenticate with
    ``X-Developer-Token`` instead of user JWTs.
    """
    from bisheng.knowledge.domain.services.knowledge_space_chat_service import KnowledgeSpaceChatService

    service = KnowledgeSpaceChatService(request=request, login_user=developer_user)
    service.version_repo = version_repo
    return service
