from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable
from sqlalchemy import Column, DateTime, text
from sqlmodel import Field, select


class ResourceTypeEnum(Enum):
    KNOWLEDGE = 1
    FLOW = 2
    ASSISTANT = 3


class GroupResourceBase(SQLModelSerializable):
    group_id: str = Field(index=True)
    third_id: str = Field(index=False)
    type: int = Field(index=False, description='1:知识库 2:工作流 3:知识库写权限 4:工作流写权限 5:助手读权限 6:助手写权限')
    create_time: Optional[datetime] = Field(sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=False,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')))


class GroupResource(GroupResourceBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)


class GroupResourceRead(GroupResourceBase):
    id: Optional[int]
    group_admins: Optional[List[Dict]]


class GroupResourceUpdate(GroupResourceBase):
    role_name: Optional[str]
    remark: Optional[str]


class GroupResourceCreate(GroupResourceBase):
    pass


class GroupResourceDao(GroupResourceBase):

    @classmethod
    def insert_group(cls, group_resource: GroupResource) -> GroupResource:
        with session_getter() as session:
            session.add(group_resource)
            session.commit()
            session.refresh(group_resource)
            return group_resource

    @classmethod
    def get_group_resource(cls,
                           group_id: int,
                           resource_type: ResourceTypeEnum,
                           name: str = None,
                           page_size: int = None,
                           page_num: int = None) -> list[GroupResource]:
        with session_getter() as session:
            statement = select(GroupResource).where(GroupResource.group_id == group_id,
                                                    GroupResource.type == resource_type.value)
            if name:
                statement = statement.where(GroupResource.third_id.like(f'%{name}%'))
            if page_num and page_size:
                statement = statement.offset(page_size * (page_num - 1)).limit(page_size)
            return session.exec(statement).all()
