from fastapi import Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.dependencies.core_deps import get_db_session
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import \
    KnowledgeFileRepositoryImpl
from bisheng.knowledge.domain.repositories.implementations.knowledge_repository_impl import KnowledgeRepositoryImpl
from bisheng.knowledge.domain.repositories.interfaces.knowledge_file_repository import KnowledgeFileRepository
from bisheng.knowledge.domain.repositories.interfaces.knowledge_repository import KnowledgeRepository
from bisheng.knowledge.domain.services.knowledge_file_service import KnowledgeFileService
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService


async def get_knowledge_repository(
        session: AsyncSession = Depends(get_db_session),
) -> KnowledgeRepository:
    """获取KnowledgeRepository实例的依赖项"""
    return KnowledgeRepositoryImpl(session)


async def get_knowledge_file_repository(
        session: AsyncSession = Depends(get_db_session),
) -> 'KnowledgeFileRepository':
    """获取KnowledgeFileRepository实例的依赖项"""

    return KnowledgeFileRepositoryImpl(session)


async def get_knowledge_service(
        knowledge_repository: KnowledgeRepository = Depends(get_knowledge_repository),
) -> 'KnowledgeService':
    """获取KnowledgeService实例的依赖项"""
    return KnowledgeService(knowledge_repository=knowledge_repository)


async def get_knowledge_file_service(
        knowledge_repository: KnowledgeRepository = Depends(get_knowledge_repository),
        knowledge_file_repository: KnowledgeFileRepository = Depends(get_knowledge_file_repository),
) -> 'KnowledgeFileService':
    """获取KnowledgeFileService实例的依赖项"""
    return KnowledgeFileService(
        knowledge_repository=knowledge_repository,
        knowledge_file_repository=knowledge_file_repository,
    )
