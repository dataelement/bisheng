from datetime import datetime
from typing import List, Optional

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable
from sqlalchemy import Column, DateTime, text
from sqlmodel import Field, select


class UserGroupBase(SQLModelSerializable):
    user_id: int = Field(index=True, description='用户id')
    group_id: int = Field(index=True, description='组id')
    is_group_admin: bool = Field(index=False, description='是否是组管理员')
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
    user_id: Optional[int]
    group_id: Optional[int]
    is_group_admin: Optional[bool]
    remark: Optional[str]


class UserGroupCreate(UserGroupBase):
    pass


class UserGroupDao(UserGroupBase):

    @classmethod
    def get_user_group(cls, user_id: int) -> List[UserGroup]:
        with session_getter() as session:
            statement = select(UserGroup).where(UserGroup.user_id == user_id)
            return session.exec(statement).all()

    @classmethod
    def insert_user_group(cls, user_group: UserGroupCreate) -> UserGroup:
        with session_getter() as session:
            session.add(user_group)
            session.commit()
            session.refresh(user_group)
            return user_group
