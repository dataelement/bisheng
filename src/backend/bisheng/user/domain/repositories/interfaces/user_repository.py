from abc import ABC

from bisheng.common.repositories.interfaces.base_repository import BaseRepository
from bisheng.department.domain.services.department_display_service import (
    DepartmentNameProjection,
)
from bisheng.user.domain.models.user import User, UserQuery


class UserRepository(BaseRepository[User, int], ABC):
    """User Repository Interface Class"""

    # accordinguser_idget user info user、user_groups、roles
    async def get_user_with_groups_and_roles_by_user_id(self, user_id: int) -> UserQuery:
        pass

    def get_user_with_groups_and_roles_by_user_id_sync(self, user_id: int) -> UserQuery:
        pass

    async def get_primary_department_name(self, user_id: int) -> str | None:
        pass

    async def get_primary_department_name_projection(
        self,
        user_id: int,
    ) -> DepartmentNameProjection | None:
        pass

    async def list_active_by_external_id(self, external_id: str) -> list[User]:
        """Return every active user matching the external ID across sources."""
        pass

    async def list_active_by_name(self, keyword: str, *, limit: int) -> list[User]:
        """返回门户安全候选构建所需的有界活动用户名称候选。"""
        pass
