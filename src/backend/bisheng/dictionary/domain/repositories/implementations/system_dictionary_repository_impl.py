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
        sort_by: bool | None = None,
        is_enabled: bool | None = None,
    ) -> tuple[list[SystemDictionary], int]:
        """分页查询字典条目,返回 (数据列表, 总数)"""
        query = select(SystemDictionary)

        if dict_type:
            query = query.where(SystemDictionary.type == dict_type)

        if keyword:
            like_pattern = f"%{keyword.strip()}%"
            query = query.where(
                (SystemDictionary.dict_key.ilike(like_pattern)) | (SystemDictionary.dict_value.ilike(like_pattern))
            )

        if is_enabled is not None:
            query = query.where(SystemDictionary.is_enabled == is_enabled)

        count_query = select(func.count()).select_from(query.subquery())
        count_result = await self.session.exec(count_query)
        total = count_result.one()

        offset = (page - 1) * page_size
        query = (
            query.order_by(
                SystemDictionary.sort_order.desc()
                if sort_by is not None and not sort_by
                else SystemDictionary.id.asc(),
                SystemDictionary.id.asc(),
            )
            .offset(offset)
            .limit(page_size)
        )
        result = await self.session.exec(query)
        return list(result.all()), total

    async def find_by_type(
        self,
        dict_type: str,
        page: int = 1,
        page_size: int = 20,
        only_enabled: bool = True,
    ) -> list[SystemDictionary]:
        """根据类型查询字典条目列表"""
        query = select(SystemDictionary).where(SystemDictionary.type == dict_type)
        if only_enabled:
            query = query.where(SystemDictionary.is_enabled == True)  # noqa: E712

        offset = (page - 1) * page_size
        query = (
            query.order_by(
                SystemDictionary.sort_order.asc(),
                SystemDictionary.id.asc(),
            )
            .offset(offset)
            .limit(page_size)
        )
        result = await self.session.exec(query)
        return list(result.all())

    async def find_all_for_export(
        self,
        dict_type: str | None = None,
        keyword: str | None = None,
        sort_by: bool | None = None,
        is_enabled: bool | None = None,
    ) -> list[SystemDictionary]:
        """查询所有字典条目用于导出,支持 type/keyword/sort_by/is_enabled 筛选"""
        query = select(SystemDictionary)

        if dict_type:
            query = query.where(SystemDictionary.type == dict_type)

        if keyword:
            like_pattern = f"%{keyword.strip()}%"
            query = query.where(
                (SystemDictionary.dict_key.ilike(like_pattern)) | (SystemDictionary.dict_value.ilike(like_pattern))
            )

        if is_enabled is not None:
            query = query.where(SystemDictionary.is_enabled == is_enabled)

        query = query.order_by(
            SystemDictionary.sort_order.desc() if sort_by is not None and not sort_by else SystemDictionary.id.asc(),
            SystemDictionary.id.asc(),
        )
        result = await self.session.exec(query)
        return list(result.all())

    async def get_max_sort_order_by_type(self, dict_type: str) -> int:
        """查询指定类型下最大的 sort_order 值,无记录时返回 0"""
        query = select(func.coalesce(func.max(SystemDictionary.sort_order), 0)).where(
            SystemDictionary.type == dict_type
        )
        result = await self.session.exec(query)
        return result.one()
