"""System Dictionary repository interface - 系统字典仓储接口"""

from abc import ABC, abstractmethod

from bisheng.common.repositories.interfaces.base_repository import BaseRepository
from bisheng.dictionary.domain.models.system_dictionary import SystemDictionary


class SystemDictionaryRepository(BaseRepository[SystemDictionary, int], ABC):
    """系统字典数据访问接口"""

    @abstractmethod
    async def find_by_type_and_key(
        self,
        dict_type: str,
        dict_key: str,
    ) -> SystemDictionary | None:
        """根据类型和键查询字典条目(用于唯一性校验)"""
        pass

    @abstractmethod
    async def find_by_key(
        self,
        dict_key: str,
    ) -> SystemDictionary | None:
        """根据键查询启用的字典条目"""
        pass

    @abstractmethod
    async def find_page(
        self,
        dict_type: str | None = None,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[SystemDictionary], int]:
        """分页查询字典条目,返回 (数据列表, 总数)"""
        pass

    @abstractmethod
    async def find_by_type(
        self,
        dict_type: str,
        only_enabled: bool = True,
    ) -> list[SystemDictionary]:
        """根据类型查询字典条目列表"""
        pass
