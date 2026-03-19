from typing import TYPE_CHECKING

from fastapi import Depends, Request
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.dependencies.core_deps import get_db_session
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import \
    KnowledgeFileRepositoryImpl
from bisheng.knowledge.domain.repositories.implementations.knowledge_repository_impl import KnowledgeRepositoryImpl
from bisheng.knowledge.domain.repositories.interfaces.knowledge_file_repository import KnowledgeFileRepository
from bisheng.knowledge.domain.repositories.interfaces.knowledge_repository import KnowledgeRepository

# Service imports are deferred to avoid circular imports
if TYPE_CHECKING:
    from bisheng.knowledge.domain.services.knowledge_file_service import KnowledgeFileService
    from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
    from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


async def get_knowledge_repository(
        session: AsyncSession = Depends(get_db_session),
) -> KnowledgeRepository:
    """DapatkanKnowledgeRepositoryInstance Dependencies"""
    return KnowledgeRepositoryImpl(session)


async def get_knowledge_file_repository(
        session: AsyncSession = Depends(get_db_session),
) -> 'KnowledgeFileRepository':
    """DapatkanKnowledgeFileRepositoryInstance Dependencies"""

    return KnowledgeFileRepositoryImpl(session)


async def get_knowledge_service(
        knowledge_repository: KnowledgeRepository = Depends(get_knowledge_repository),
        knowledge_file_repository: KnowledgeFileRepository = Depends(get_knowledge_file_repository),
) -> 'KnowledgeService':
    """DapatkanKnowledgeServiceInstance Dependencies"""
    from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService as _KnowledgeService
    return _KnowledgeService(knowledge_repository=knowledge_repository,
                             knowledge_file_repository=knowledge_file_repository)


async def get_knowledge_file_service(
        knowledge_repository: KnowledgeRepository = Depends(get_knowledge_repository),
        knowledge_file_repository: KnowledgeFileRepository = Depends(get_knowledge_file_repository),
) -> 'KnowledgeFileService':
    """DapatkanKnowledgeFileServiceInstance Dependencies"""
    from bisheng.knowledge.domain.services.knowledge_file_service import KnowledgeFileService as _KnowledgeFileService
    return _KnowledgeFileService(
        knowledge_repository=knowledge_repository,
        knowledge_file_repository=knowledge_file_repository,
    )


def get_knowledge_space_service(
        request: Request,
        login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> 'KnowledgeSpaceService':
    """Get KnowledgeSpaceService instance, bound to the current request and login user"""
    from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService as _SvcClass
    return _SvcClass(request=request, login_user=login_user)
