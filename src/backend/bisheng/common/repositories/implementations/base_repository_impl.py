from typing import Type, TypeVar, Optional, Any, Sequence

from sqlalchemy import Row, RowMapping, func
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.repositories.interfaces.base_repository import BaseRepository

T = TypeVar('T', bound=SQLModel)
ID = TypeVar('ID')


class BaseRepositoryImpl(BaseRepository[T, ID]):
    """Repository基础实现"""

    def __init__(self, session: AsyncSession, model_class: Type[T]):
        self.session = session
        self.model_class = model_class

    async def save(self, entity: T) -> T:
        """保存实体"""
        self.session.add(entity)
        await self.session.commit()
        await self.session.refresh(entity)
        return entity

    async def find_by_id(self, entity_id: ID) -> Optional[T]:
        """根据ID查找实体"""
        entity = await self.session.get_one(entity_id)
        return entity

    async def find_one(self, **filters) -> Optional[T]:
        """查找单个实体"""
        query = select(self.model_class)

        # 应用过滤条件
        for field, value in filters.items():
            if hasattr(self.model_class, field):
                query = query.where(getattr(self.model_class, field) == value)
        result = await self.session.exec(query)
        return result.first()

    async def find_all(self, **filters) -> Sequence[Row[Any] | RowMapping | Any]:
        """查找所有实体"""
        query = select(self.model_class)

        # 应用过滤条件
        for field, value in filters.items():
            if hasattr(self.model_class, field):
                query = query.where(getattr(self.model_class, field) == value)
        result = await self.session.exec(query)
        return result.all()

    async def update(self, entity: T) -> T:
        """更新实体"""
        merged_entity = await self.session.merge(entity)
        await self.session.commit()
        await self.session.refresh(merged_entity)
        return merged_entity

    async def delete(self, entity_id: ID) -> bool:
        """删除实体"""
        entity = await self.find_by_id(entity_id)
        if entity:
            await self.session.delete(entity)
            await self.session.commit()
            return True
        return False

    async def exists(self, entity_id: ID) -> bool:
        """检查实体是否存在"""
        entity = await self.find_by_id(entity_id)
        return entity is not None

    async def count(self, **filters) -> int:
        """统计实体数量"""
        query = select(self.model_class)

        # 应用过滤条件
        for field, value in filters.items():
            if hasattr(self.model_class, field):
                query = query.where(getattr(self.model_class, field) == value)

        count_q = query.with_only_columns(func.count()).order_by(None).select_from(query.get_final_froms()[0])

        result = await self.session.exec(count_q)

        for count in result:
            return count
        return 0
