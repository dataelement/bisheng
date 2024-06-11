from datetime import datetime
from typing import List, Optional

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable
from pydantic import BaseModel
from sqlalchemy import Column, DateTime, text
from sqlmodel import Field, select


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
