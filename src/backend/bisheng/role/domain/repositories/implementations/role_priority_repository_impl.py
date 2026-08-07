from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.repositories.implementations.base_repository_impl import (
    BaseRepositoryImpl,
)
from bisheng.database.models.role import Role
from bisheng.role.domain.repositories.interfaces.role_priority_repository import (
    RolePriorityRepository,
)
from bisheng.user.domain.models.user import User
from bisheng.user.domain.models.user_role import UserRole


class RolePriorityRepositoryImpl(
    BaseRepositoryImpl[Role, int],
    RolePriorityRepository,
):
    """SQLModel implementation; tenant filtering is injected by SQLAlchemy events."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, Role)

    async def user_exists(self, user_id: int) -> bool:
        result = await self.session.execute(
            select(User.user_id).where(
                User.user_id == user_id,
                User.delete == 0,
            )
        )
        return result.scalar_one_or_none() is not None

    async def list_role_quota_configs(
        self,
        user_id: int,
    ) -> list[dict | None]:
        result = await self.session.execute(
            select(Role.quota_config).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user_id)
        )
        return list(result.scalars().all())
