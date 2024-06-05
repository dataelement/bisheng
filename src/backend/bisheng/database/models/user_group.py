from datetime import datetime
from typing import Optional

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable
from sqlalchemy import Column, DateTime, text
from sqlmodel import Field, select


class UserGroupBase(SQLModelSerializable):
    group_name: str = Field(index=False, description='前端展示名称', unique=True)
    remark: Optional[str] = Field(index=False)
    create_time: Optional[datetime] = Field(sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=False,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')))


class UserGroup(UserGroupBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)


class UserGroupRead(UserGroupBase):
    id: Optional[int]


class UserGroupUpdate(UserGroupBase):
    role_name: Optional[str]
    remark: Optional[str]


class UserGroupCreate(UserGroupBase):
    pass


class UserGroupDao(UserGroupBase):

    @classmethod
    def get_user_group(cls, user_id: int):
        with session_getter() as session:
            statement = select(UserGroup).where(UserGroup.user_id == user_id)
            return session.exec(statement).all()
