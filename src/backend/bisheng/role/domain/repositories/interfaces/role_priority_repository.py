from abc import ABC, abstractmethod

from bisheng.common.repositories.interfaces.base_repository import BaseRepository
from bisheng.database.models.role import Role


class RolePriorityRepository(BaseRepository[Role, int], ABC):
    """Read the current tenant's role priority metadata for one user."""

    @abstractmethod
    async def user_exists(self, user_id: int) -> bool: ...

    @abstractmethod
    async def list_role_quota_configs(
        self,
        user_id: int,
    ) -> list[dict | None]: ...
