from typing import Annotated, Union

from fastapi import Depends, Header
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.dependencies.core_deps import get_db_session
from bisheng.knowledge.domain.repositories.implementations.knowledge_repository_impl import KnowledgeRepositoryImpl
from bisheng.knowledge.domain.repositories.interfaces.knowledge_repository import KnowledgeRepository
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService


async def get_knowledge_repository(
        session: AsyncSession = Depends(get_db_session),
) -> KnowledgeRepository:
    """获取KnowledgeRepository实例的依赖项"""
    return KnowledgeRepositoryImpl(session)


async def get_knowledge_service(
        knowledge_repository: KnowledgeRepository = Depends(get_knowledge_repository),
) -> 'KnowledgeService':
    """获取KnowledgeService实例的依赖项"""
    return KnowledgeService(knowledge_repository=knowledge_repository)
