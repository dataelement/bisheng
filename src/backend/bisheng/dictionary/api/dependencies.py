"""Dictionary API dependencies - 字典模块依赖注入"""

from fastapi import Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.dependencies.core_deps import get_db_session
from bisheng.dictionary.domain.repositories.implementations.system_dictionary_repository_impl import (
    SystemDictionaryRepositoryImpl,
)
from bisheng.dictionary.domain.repositories.interfaces.system_dictionary_repository import (
    SystemDictionaryRepository,
)
from bisheng.dictionary.domain.services.dictionary_service import DictionaryService


async def get_system_dictionary_repository(
    session: AsyncSession = Depends(get_db_session),
) -> SystemDictionaryRepository:
    """提供 SystemDictionaryRepository 实例"""
    return SystemDictionaryRepositoryImpl(session)


async def get_dictionary_service(
    repository: SystemDictionaryRepository = Depends(get_system_dictionary_repository),
) -> DictionaryService:
    """提供 DictionaryService 实例"""
    return DictionaryService(repository)
