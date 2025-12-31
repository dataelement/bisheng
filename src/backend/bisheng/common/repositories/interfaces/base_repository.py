from abc import ABC, abstractmethod
from typing import Generic, TypeVar, List, Optional, Dict, Any

T = TypeVar('T')
ID = TypeVar('ID')


class BaseRepository(ABC, Generic[T, ID]):
    """Repository基础接口"""

    @abstractmethod
    async def save(self, entity: T) -> T:
        """保存实体"""
        pass

    @abstractmethod
    async def bulk_save(self, entities: List[T]) -> List[T]:
        """批量保存实体"""
        pass

    @abstractmethod
    def save_sync(self, entity: T) -> T:
        """同步保存实体"""
        pass

    @abstractmethod
    def bulk_save_sync(self, entities: List[T]) -> List[T]:
        """同步批量保存实体"""
        pass

    @abstractmethod
    async def find_by_id(self, entity_id: ID) -> Optional[T]:
        """根据ID查找实体"""
        pass

    @abstractmethod
    def find_by_id_sync(self, entity_id: ID) -> Optional[T]:
        """同步根据ID查找实体"""
        pass

    @abstractmethod
    async def find_one(self, **filters) -> Optional[T]:
        """查找单个实体"""
        pass

    @abstractmethod
    def find_one_sync(self, **filters) -> Optional[T]:
        """同步查找单个实体"""
        pass

    @abstractmethod
    async def find_by_ids(self, entity_ids: List[ID]) -> List[T]:
        """根据多个ID查找实体"""
        pass

    @abstractmethod
    def find_by_ids_sync(self, entity_ids: List[ID]) -> List[T]:
        """同步根据多个ID查找实体"""
        pass

    @abstractmethod
    async def find_all(self, **filters) -> List[T]:
        """查找所有实体"""
        pass

    @abstractmethod
    def find_all_sync(self, **filters) -> List[T]:
        """同步查找所有实体"""
        pass

    @abstractmethod
    async def update(self, entity: T) -> T:
        """更新实体"""
        pass

    @abstractmethod
    def update_sync(self, entity: T) -> T:
        """同步更新实体"""
        pass

    @abstractmethod
    async def delete(self, entity_id: ID) -> bool:
        """删除实体"""
        pass

    @abstractmethod
    def delete_sync(self, entity_id: ID) -> bool:
        """同步删除实体"""
        pass

    @abstractmethod
    async def exists(self, entity_id: ID) -> bool:
        """检查实体是否存在"""
        pass

    @abstractmethod
    def exists_sync(self, entity_id: ID) -> bool:
        """同步检查实体是否存在"""
        pass

    @abstractmethod
    async def count(self, **filters) -> int:
        """统计实体数量"""
        pass

    @abstractmethod
    def count_sync(self, **filters) -> int:
        """同步统计实体数量"""
        pass
