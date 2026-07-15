from abc import ABC, abstractmethod
from typing import Any

from bisheng.common.repositories.interfaces.base_repository import BaseRepository


class KnowledgeSpacePinRepository(BaseRepository[Any, int], ABC):
    @abstractmethod
    async def lock_user(self, user_id: int) -> None: ...

    @abstractmethod
    async def list_for_user(self, user_id: int) -> set[int]: ...

    @abstractmethod
    async def add_pin(self, user_id: int, space_id: int) -> bool: ...

    @abstractmethod
    async def remove_pin(self, user_id: int, space_id: int) -> bool: ...

    @abstractmethod
    async def delete_by_space_id(self, space_id: int) -> int: ...
