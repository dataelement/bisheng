from datetime import datetime
from typing import List, Optional

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable
from pydantic import BaseModel
from sqlalchemy import Column, DateTime, text, delete
from sqlmodel import Field, select

from bisheng.database.models.role import AdminRole


class UserRoleBase(SQLModelSerializable):
    user_id: int = Field(index=True)
    role_id: int = Field(index=True)
    create_time: Optional[datetime] = Field(
        sa_column=Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=False,
                         index=True,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')))


class UserRole(UserRoleBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)


class UserRoleRead(UserRoleBase):
    id: Optional[int]


class UserRoleCreate(BaseModel):
    user_id: int
    role_id: list[int]


class UserRoleDao(UserRoleBase):

    @classmethod
    def get_user_roles(cls, user_id: int) -> List[UserRole]:
        with session_getter() as session:
            return session.exec(select(UserRole).where(UserRole.user_id == user_id)).all()

    @classmethod
    def get_roles_user(cls, role_ids: List[int], page: int = 0, limit: int = 0) -> List[UserRole]:
        """
        获取角色对应的用户
        """
        with session_getter() as session:
            statement = select(UserRole).where(UserRole.role_id.in_(role_ids))
            if page and limit:
                statement = statement.offset((page - 1) * limit).limit(limit)
            return session.exec(statement).all()

    @classmethod
    def get_admins_user(cls) -> List[UserRole]:
        """
        获取所有超级管理的账号
        """
        with session_getter() as session:
            statement = select(UserRole).where(UserRole.role_id == AdminRole)
            return session.exec(statement).all()

    @classmethod
    def set_admin_user(cls, user_id: int) -> UserRole:
        """
        设置用户为超级管理员
        """
        with session_getter() as session:
            user_role = UserRole(user_id=user_id, role_id=AdminRole)
            session.add(user_role)
            session.commit()
            session.refresh(user_role)
            return user_role

    @classmethod
    def add_user_roles(cls, user_id: int, role_ids: List[int]) -> List[UserRole]:
        """
        给用户批量添加角色
        """
        with session_getter() as session:
            user_roles = [UserRole(user_id=user_id, role_id=role_id) for role_id in role_ids]
            session.add_all(user_roles)
            session.commit()
            return user_roles

    @classmethod
    def delete_user_roles(cls, user_id: int, role_ids: List[int]) -> None:
        """
        将用户从某些角色中移除
        """
        with session_getter() as session:
            statement = delete(UserRole).where(UserRole.user_id == user_id).where(UserRole.role_id.in_(role_ids))
            session.exec(statement)
            session.commit()
