from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable
from sqlalchemy import Column, DateTime, text, delete
from sqlmodel import Field, select


class ResourceTypeEnum(Enum):
    KNOWLEDGE = 1
    FLOW = 2
    ASSISTANT = 3
    GPTS_TOOL = 4
    WORK_FLOW= 5


class GroupResourceBase(SQLModelSerializable):
    group_id: str = Field(index=True)
    third_id: str = Field(index=False)
    type: int = Field(index=False, description='资源类别 1:知识库 2:技能 3:助手 4:工具 5:工作流')
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
    def insert_group_batch(cls, group_resources: List[GroupResource]) -> List[GroupResource]:
        with session_getter() as session:
            session.add_all(group_resources)
            session.commit()
            return group_resources

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

    @classmethod
    def get_groups_resource(cls,
                            group_ids: List[int],
                            resource_types: List[ResourceTypeEnum] = None,
                            name: str = None,
                            page_size: int = None,
                            page_num: int = None) -> list[GroupResource]:
        with session_getter() as session:
            statement = select(GroupResource).where(GroupResource.group_id.in_(group_ids))
            if resource_types:
                statement = statement.where(GroupResource.type.in_([r.value for r in resource_types]))
            if name:
                statement = statement.where(GroupResource.third_id.like(f'%{name}%'))
            if page_num and page_size:
                statement = statement.offset(page_size * (page_num - 1)).limit(page_size)
            return session.exec(statement).all()

    @classmethod
    def get_resource_group(cls, resource_type: ResourceTypeEnum, third_id: str) -> list[GroupResource]:
        """
        获取资源所属的分组
        """
        with session_getter() as session:
            statement = select(GroupResource).where(GroupResource.third_id == third_id,
                                                    GroupResource.type == resource_type.value)
            return session.exec(statement).all()

    @classmethod
    def get_resources_group(cls, resource_type: ResourceTypeEnum, third_ids: List[str]) -> list[GroupResource]:
        """
        获取批量资源所属的分组
        """
        with session_getter() as session:
            statement = select(GroupResource).where(GroupResource.third_id.in_(third_ids),
                                                    GroupResource.type == resource_type.value)
            return session.exec(statement).all()

    @classmethod
    def delete_group_resource_by_third_id(cls, third_id: str, resource_type: ResourceTypeEnum) -> None:
        with (session_getter() as session):
            statement = delete(GroupResource).where(
                GroupResource.third_id == third_id).where(
                GroupResource.type == resource_type.value)
            session.exec(statement)
            session.commit()

    @classmethod
    def delete_group_resource_by_group_id(cls, group_id: int):
        with (session_getter() as session):
            statement = delete(GroupResource).where(GroupResource.group_id == group_id)
            session.exec(statement)
            session.commit()

    @classmethod
    def get_group_all_resource(cls, group_id: int) -> List[GroupResource]:
        """
        获取分组下的所有资源
        """
        with session_getter() as session:
            return session.exec(
                select(GroupResource).where(GroupResource.group_id == group_id)).all()

    @classmethod
    def update_group_resource(cls, group_resources: List[GroupResource]) -> List[GroupResource]:
        with (session_getter() as session):
            session.add_all(group_resources)
            session.commit()
        return group_resources
