from typing import Type, TypeVar, Optional, Any, Sequence, Union, List, Coroutine

from sqlalchemy import Row, RowMapping, func
from sqlmodel import SQLModel, select, Session, col
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.repositories.interfaces.base_repository import BaseRepository

T = TypeVar('T', bound=SQLModel)
ID = TypeVar('ID')


class BaseRepositoryImpl(BaseRepository[T, ID]):
    """RepositoryBasic Implementation"""

    def __init__(self, session: Union[AsyncSession, Session], model_class: Type[T]):
        self.session = session
        self.model_class = model_class

    async def save(self, entity: T) -> T:
        """Save Entity"""
        self.session.add(entity)
        await self.session.commit()
        await self.session.refresh(entity)
        return entity

    async def bulk_save(self, entities: List[T]) -> List[T]:
        """Batch Save Entities"""
        self.session.add_all(entities)
        await self.session.commit()
        for entity in entities:
            await self.session.refresh(entity)
        return entities

    def save_sync(self, entity: T) -> T:
        """Synchronous Save Entity"""
        self.session.add(entity)
        self.session.commit()
        self.session.refresh(entity)
        return entity

    def bulk_save_sync(self, entities: List[T]) -> List[T]:
        """Synchronize Batch Save Entities"""
        self.session.add_all(entities)
        self.session.commit()
        for entity in entities:
            self.session.refresh(entity)
        return entities

    async def find_by_id(self, entity_id: ID) -> Optional[T]:
        """accordingIDFind Entity"""
        entity = await self.session.get(self.model_class, entity_id)
        return entity

    def find_by_id_sync(self, entity_id: ID) -> Optional[T]:
        """Sync byIDFind Entity"""
        entity = self.session.get(self.model_class, entity_id)
        return entity

    async def find_one(self, **filters) -> Optional[T]:
        """Find a single entity"""
        query = select(self.model_class)

        # Apply Filter Criteria
        for field, value in filters.items():
            if hasattr(self.model_class, field):
                query = query.where(getattr(self.model_class, field) == value)
        result = await self.session.exec(query)
        return result.first()

    def find_one_sync(self, **filters) -> Optional[T]:
        """Synchronous lookup of a single entity"""
        query = select(self.model_class)

        # Apply Filter Criteria
        for field, value in filters.items():
            if hasattr(self.model_class, field):
                query = query.where(getattr(self.model_class, field) == value)
        result = self.session.exec(query)
        return result.first()

    async def find_by_ids(self, entity_ids: List[ID]) -> Sequence[Row[Any] | RowMapping | Any]:
        """According to multipleIDFind Entity"""
        query = select(self.model_class).where(col(self.model_class.id).in_(entity_ids))
        result = await self.session.exec(query)
        return result.all()

    def find_by_ids_sync(self, entity_ids: List[ID]) -> Sequence[Row[Any] | RowMapping | Any]:
        """Sync based on multipleIDFind Entity"""
        query = select(self.model_class).where(col(self.model_class.id).in_(entity_ids))
        result = self.session.exec(query)
        return result.all()

    async def find_all(self, **filters) -> Sequence[Row[Any] | RowMapping | Any]:
        """Find all entities"""
        query = select(self.model_class)

        # Apply Filter Criteria
        for field, value in filters.items():
            if hasattr(self.model_class, field):
                query = query.where(getattr(self.model_class, field) == value)
        result = await self.session.exec(query)
        return result.all()

    def find_all_sync(self, **filters) -> Sequence[Row[Any] | RowMapping | Any]:
        """Sync Find All Entities"""
        query = select(self.model_class)

        # Apply Filter Criteria
        for field, value in filters.items():
            if hasattr(self.model_class, field):
                query = query.where(getattr(self.model_class, field) == value)
        result = self.session.exec(query)
        return result.all()

    async def update(self, entity: T) -> T:
        """Update entities"""
        merged_entity = await self.session.merge(entity)
        await self.session.commit()
        await self.session.refresh(merged_entity)
        return merged_entity

    def update_sync(self, entity: T) -> T:
        """Synchronize Update Entities"""
        merged_entity = self.session.merge(entity)
        self.session.commit()
        self.session.refresh(merged_entity)
        return merged_entity

    async def delete(self, entity_id: ID) -> bool:
        """Delete entity role"""
        entity = await self.find_by_id(entity_id)
        if entity:
            await self.session.delete(entity)
            await self.session.commit()
            return True
        return False

    def delete_sync(self, entity_id: ID) -> bool:
        """Synchronous deletion of entities"""
        entity = self.find_by_id_sync(entity_id)
        if entity:
            self.session.delete(entity)
            self.session.commit()
            return True
        return False

    async def exists(self, entity_id: ID) -> bool:
        """Check if the entity exists"""
        entity = await self.find_by_id(entity_id)
        return entity is not None

    def exists_sync(self, entity_id: ID) -> bool:
        """Synchronization Check Entity Existence"""
        entity = self.find_by_id_sync(entity_id)
        return entity is not None

    async def count(self, **filters) -> int:
        """Number of statistical entities"""
        query = select(self.model_class)

        # Apply Filter Criteria
        for field, value in filters.items():
            if hasattr(self.model_class, field):
                query = query.where(getattr(self.model_class, field) == value)

        count_q = query.with_only_columns(func.count()).order_by(None).select_from(query.get_final_froms()[0])

        result = await self.session.exec(count_q)

        for count in result:
            return count
        return 0

    def count_sync(self, **filters) -> int:
        """Number of entities synchronized"""
        query = select(self.model_class)

        # Apply Filter Criteria
        for field, value in filters.items():
            if hasattr(self.model_class, field):
                query = query.where(getattr(self.model_class, field) == value)

        count_q = query.with_only_columns(func.count()).order_by(None).select_from(query.get_final_froms()[0])

        result = self.session.exec(count_q)

        for count in result:
            return count
        return 0
