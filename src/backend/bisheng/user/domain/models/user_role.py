from pydantic import BaseModel
from sqlalchemy import delete
from sqlmodel import select

from bisheng.core.database import get_async_db_session, get_sync_db_session
from bisheng.database.constants import AdminRole
from bisheng.database.models.user_role import UserRole, UserRoleBase


class UserRoleRead(UserRoleBase):
    id: int | None = None


class UserRoleCreate(BaseModel):
    user_id: int
    role_id: list[int]


class UserRoleDao(UserRoleBase):
    @classmethod
    def get_user_roles(cls, user_id: int) -> list[UserRole]:
        with get_sync_db_session() as session:
            return session.exec(select(UserRole).where(UserRole.user_id == user_id)).all()

    @classmethod
    async def aget_user_roles(cls, user_id: int) -> list[UserRole]:
        async with get_async_db_session() as session:
            result = await session.exec(select(UserRole).where(UserRole.user_id == user_id))
            return result.all()

    @classmethod
    def get_roles_user(cls, role_ids: list[int], page: int = 0, limit: int = 0) -> list[UserRole]:
        """
        Get the user for the role
        """
        with get_sync_db_session() as session:
            statement = select(UserRole).where(UserRole.role_id.in_(role_ids))
            if page and limit:
                statement = statement.offset((page - 1) * limit).limit(limit)
            return session.exec(statement).all()

    @classmethod
    async def aget_roles_user(cls, role_ids: list[int]) -> list[UserRole]:
        async with get_async_db_session() as session:
            result = await session.exec(select(UserRole).where(UserRole.role_id.in_(role_ids)))
            return result.all()

    @classmethod
    def get_admins_user(cls) -> list[UserRole]:
        """
        Get all super-managed accounts
        """
        with get_sync_db_session() as session:
            statement = select(UserRole).where(UserRole.role_id == AdminRole)
            return session.exec(statement).all()

    @classmethod
    async def set_admin_user(cls, user_id: int) -> UserRole:
        """
        Set user as Super Admin
        """
        async with get_async_db_session() as session:
            user_role = UserRole(user_id=user_id, role_id=AdminRole)
            session.add(user_role)
            await session.commit()
            await session.refresh(user_role)
            return user_role

    @classmethod
    def add_user_roles(cls, user_id: int, role_ids: list[int]) -> list[UserRole]:
        """
        Add roles to users in bulk
        """
        with get_sync_db_session() as session:
            user_roles = [UserRole(user_id=user_id, role_id=role_id) for role_id in role_ids]
            session.add_all(user_roles)
            session.commit()
            return user_roles

    @classmethod
    def delete_user_roles(cls, user_id: int, role_ids: list[int]) -> None:
        """
        Remove users from certain roles
        """
        with get_sync_db_session() as session:
            statement = delete(UserRole).where(UserRole.user_id == user_id).where(UserRole.role_id.in_(role_ids))
            session.exec(statement)
            session.commit()
