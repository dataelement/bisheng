from datetime import datetime
from typing import List, Optional

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable
from sqlalchemy import Column, DateTime, text
from sqlmodel import Field, select


class GroupBase(SQLModelSerializable):
    group_name: str = Field(index=False, description='前端展示名称', unique=True)
    remark: Optional[str] = Field(index=False)
    create_time: Optional[datetime] = Field(sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=False,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')))


class Group(GroupBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)


class GroupRead(GroupBase):
    id: Optional[int]
    group_admins: Optional[List[str]]


class GroupUpdate(GroupBase):
    role_name: Optional[str]
    remark: Optional[str]


class GroupCreate(GroupBase):
    pass


class GroupDao(GroupBase):

    @classmethod
    def get_user_group(cls, group_id: int) -> Group | None:
        with session_getter() as session:
            statement = select(Group).where(Group.id == group_id)
            return session.exec(statement).first()

    @classmethod
    def insert_group(cls, group: GroupCreate) -> Group:
        with session_getter() as session:
            session.add(group)
            session.commit()
            session.refresh(group)
            return group

    @classmethod
    def get_all_group(cls) -> list[Group]:
        with session_getter() as session:
            statement = select(Group)
            return session.exec(statement).all()

    @classmethod
    def get_group_by_ids(cls, ids: List[int]) -> list[Group]:
        if not ids:
            raise ValueError('ids is empty')
        with session_getter() as session:
            statement = select(Group).where(Group.id.in_(ids))
            return session.exec(statement).all()
