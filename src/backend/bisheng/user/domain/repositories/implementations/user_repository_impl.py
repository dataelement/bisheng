from typing import Union

from sqlalchemy.orm import selectinload
from sqlmodel import select, Session
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl
from bisheng.database.models.department import Department, UserDepartment
from bisheng.user.domain.models.user import User
from bisheng.user.domain.repositories.interfaces.user_repository import UserRepository


class UserRepositoryImpl(BaseRepositoryImpl[User, int], UserRepository):
    """Shared link repository implementation"""

    def __init__(self, session: Union[AsyncSession, Session]):
        super().__init__(session, User)

    async def _load_user_departments(self, user: User) -> None:
        """Load department info for a user via explicit query (UserDepartment lacks FK annotations)."""
        result = await self.session.exec(
            select(UserDepartment).where(UserDepartment.user_id == user.user_id)
        )
        ud_rows = result.all()
        if ud_rows:
            dept_ids = [ud.department_id for ud in ud_rows]
            dept_result = await self.session.exec(
                select(Department).where(Department.id.in_(dept_ids))
            )
            user.departments = dept_result.all()
        else:
            user.departments = []

    def _load_user_departments_sync(self, user: User) -> None:
        """Load department info for a user via explicit query (sync)."""
        ud_rows = self.session.exec(
            select(UserDepartment).where(UserDepartment.user_id == user.user_id)
        ).all()
        if ud_rows:
            dept_ids = [ud.department_id for ud in ud_rows]
            user.departments = self.session.exec(
                select(Department).where(Department.id.in_(dept_ids))
            ).all()
        else:
            user.departments = []

    async def get_user_with_groups_and_roles_by_user_id(self, user_id: int) -> User | None:
        statement = (
            select(User).where(User.user_id == user_id).options(
                selectinload(User.groups),  # type: ignore
                selectinload(User.roles)  # type: ignore
            )
        )

        result = await self.session.exec(statement)
        user = result.first()
        if user:
            await self._load_user_departments(user)
        return user

    def get_user_with_groups_and_roles_by_user_id_sync(self, user_id: int) -> User | None:
        statement = (
            select(User).where(User.user_id == user_id).options(
                selectinload(User.groups),  # type: ignore
                selectinload(User.roles)  # type: ignore
            )
        )

        result = self.session.exec(statement)
        user = result.first()
        if user:
            self._load_user_departments_sync(user)
        return user
