from abc import ABC, abstractmethod
from typing import Generic, TypeVar, List, Optional, Dict, Any

T = TypeVar('T')
ID = TypeVar('ID')


class BaseRepository(ABC, Generic[T, ID]):
    """RepositoryBase Interface"""

    @abstractmethod
    async def save(self, entity: T) -> T:
        """Save Entity"""
        pass

    @abstractmethod
    async def bulk_save(self, entities: List[T]) -> List[T]:
        """Batch Save Entities"""
        pass

    @abstractmethod
    def save_sync(self, entity: T) -> T:
        """Synchronous Save Entity"""
        pass

    @abstractmethod
    def bulk_save_sync(self, entities: List[T]) -> List[T]:
        """Synchronize Batch Save Entities"""
        pass

    @abstractmethod
    async def find_by_id(self, entity_id: ID) -> Optional[T]:
        """accordingIDFind Entity"""
        pass

    @abstractmethod
    def find_by_id_sync(self, entity_id: ID) -> Optional[T]:
        """Sync byIDFind Entity"""
        pass

    @abstractmethod
    async def find_one(self, **filters) -> Optional[T]:
        """Find a single entity"""
        pass

    @abstractmethod
    def find_one_sync(self, **filters) -> Optional[T]:
        """Synchronous lookup of a single entity"""
        pass

    @abstractmethod
    async def find_by_ids(self, entity_ids: List[ID]) -> List[T]:
        """According to multipleIDFind Entity"""
        pass

    @abstractmethod
    def find_by_ids_sync(self, entity_ids: List[ID]) -> List[T]:
        """Sync based on multipleIDFind Entity"""
        pass

    @abstractmethod
    async def find_all(self, **filters) -> List[T]:
        """Find all entities"""
        pass

    @abstractmethod
    def find_all_sync(self, **filters) -> List[T]:
        """Sync Find All Entities"""
        pass

    @abstractmethod
    async def update(self, entity: T) -> T:
        """Update entities"""
        pass

    @abstractmethod
    def update_sync(self, entity: T) -> T:
        """Synchronize Update Entities"""
        pass

    @abstractmethod
    async def delete(self, entity_id: ID) -> bool:
        """Delete entity role"""
        pass

    @abstractmethod
    def delete_sync(self, entity_id: ID) -> bool:
        """Synchronous deletion of entities"""
        pass

    @abstractmethod
    async def exists(self, entity_id: ID) -> bool:
        """Check if the entity exists"""
        pass

    @abstractmethod
    def exists_sync(self, entity_id: ID) -> bool:
        """Synchronization Check Entity Existence"""
        pass

    @abstractmethod
    async def count(self, **filters) -> int:
        """Number of statistical entities"""
        pass

    @abstractmethod
    def count_sync(self, **filters) -> int:
        """Number of entities synchronized"""
        pass
