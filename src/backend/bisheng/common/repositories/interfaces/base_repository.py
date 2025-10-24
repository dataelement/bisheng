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
    async def find_by_id(self, entity_id: ID) -> Optional[T]:
        """根据ID查找实体"""
        pass

    @abstractmethod
    async def find_one(self, **filters) -> Optional[T]:
        """查找单个实体"""
        pass

    @abstractmethod
    async def find_all(self, **filters) -> List[T]:
        """查找所有实体"""
        pass

    @abstractmethod
    async def update(self, entity: T) -> T:
        """更新实体"""
        pass

    @abstractmethod
    async def delete(self, entity_id: ID) -> bool:
        """删除实体"""
        pass

    @abstractmethod
    async def exists(self, entity_id: ID) -> bool:
        """检查实体是否存在"""
        pass

    @abstractmethod
    async def count(self, **filters) -> int:
        """统计实体数量"""
        pass
