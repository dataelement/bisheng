from typing import Union

from sqlalchemy.orm import selectinload
from sqlmodel import select, Session
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl
from bisheng.user.domain.models.user import User
from bisheng.user.domain.repositories.interfaces.user_repository import UserRepository


class UserRepositoryImpl(BaseRepositoryImpl[User, int], UserRepository):
    """Shared link repository implementation"""

    def __init__(self, session: Union[AsyncSession, Session]):
        super().__init__(session, User)

    # accordinguser_idget user info user、user_groups、roles
    async def get_user_with_groups_and_roles_by_user_id(self, user_id: int) -> User | None:
        statement = (
            select(User).where(User.user_id == user_id).options(
                selectinload(User.groups),  # type: ignore
                selectinload(User.roles)  # type: ignore
            )
        )

        result = await self.session.exec(statement)
        return result.first()

    def get_user_with_groups_and_roles_by_user_id_sync(self, user_id: int) -> User | None:
        statement = (
            select(User).where(User.user_id == user_id).options(
                selectinload(User.groups),  # type: ignore
                selectinload(User.roles)  # type: ignore
            )
        )

        result = self.session.exec(statement)
        return result.first()
