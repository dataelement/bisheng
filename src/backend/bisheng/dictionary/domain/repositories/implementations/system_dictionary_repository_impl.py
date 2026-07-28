"""System Dictionary repository implementation - 系统字典仓储实现"""

from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl
from bisheng.dictionary.domain.models.system_dictionary import SystemDictionary
from bisheng.dictionary.domain.repositories.interfaces.system_dictionary_repository import (
    SystemDictionaryRepository,
)


class SystemDictionaryRepositoryImpl(BaseRepositoryImpl[SystemDictionary, int], SystemDictionaryRepository):
    """系统字典数据访问实现"""

    def __init__(self, session: AsyncSession):
        super().__init__(session, SystemDictionary)

    async def find_by_type_and_key(
        self,
        dict_type: str,
        dict_key: str,
    ) -> SystemDictionary | None:
        """根据类型和键查询字典条目(用于唯一性校验)"""
        query = (
            select(SystemDictionary)
            .where(SystemDictionary.type == dict_type)
            .where(SystemDictionary.dict_key == dict_key)
        )
        result = await self.session.exec(query)
        return result.first()

    async def find_by_key(
        self,
        dict_key: str,
    ) -> SystemDictionary | None:
        """根据键查询启用的字典条目"""
        query = (
            select(SystemDictionary)
            .where(SystemDictionary.dict_key == dict_key)
            .where(SystemDictionary.is_enabled == True)  # noqa: E712
        )
        result = await self.session.exec(query)
        return result.first()

    async def find_page(
        self,
        dict_type: str | None = None,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[SystemDictionary], int]:
        """分页查询字典条目,返回 (数据列表, 总数)"""
        query = select(SystemDictionary)

        if dict_type:
            query = query.where(SystemDictionary.type == dict_type)

        if keyword:
            like_pattern = f"%{keyword.strip()}%"
            query = query.where(
                (SystemDictionary.type.ilike(like_pattern))
                | (SystemDictionary.dict_key.ilike(like_pattern))
                | (SystemDictionary.dict_value.ilike(like_pattern))
            )

        count_query = select(func.count()).select_from(query.subquery())
        count_result = await self.session.exec(count_query)
        total = count_result.one()

        offset = (page - 1) * page_size
        query = (
            query.order_by(
                SystemDictionary.sort_order.asc(),
                SystemDictionary.id.desc(),
            )
            .offset(offset)
            .limit(page_size)
        )
        result = await self.session.exec(query)
        return list(result.all()), total

    async def find_by_type(
        self,
        dict_type: str,
        only_enabled: bool = True,
    ) -> list[SystemDictionary]:
        """根据类型查询字典条目列表"""
        query = select(SystemDictionary).where(SystemDictionary.type == dict_type)
        if only_enabled:
            query = query.where(SystemDictionary.is_enabled == True)  # noqa: E712
        query = query.order_by(
            SystemDictionary.sort_order.asc(),
            SystemDictionary.id.asc(),
        )
        result = await self.session.exec(query)
        return list(result.all())
