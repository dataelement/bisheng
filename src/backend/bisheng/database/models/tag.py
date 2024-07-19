from datetime import datetime
from typing import Optional, List, Dict

from sqlalchemy import Column, DateTime, UniqueConstraint
from sqlmodel import Field, select, delete, and_, func, text

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable
from bisheng.database.models.group_resource import ResourceTypeEnum


class TagBase(SQLModelSerializable):
    """
    标签表
    """
    name: Optional[str] = Field(index=True, unique=True, description="标签名称")
    user_id: int = Field(default=0, description='创建用户ID')
    create_time: Optional[datetime] = Field(sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')), description="创建时间")
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=False,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')), description="更新时间")


class Tag(TagBase, table=True):
    id: Optional[int] = Field(index=True, primary_key=True, description="标签唯一ID")


class TagLinkBase(SQLModelSerializable):
    """
    标签关联表
    """
    tag_id: int = Field(index=True, description="标签ID")
    resource_id: str = Field(description="资源唯一ID")
    resource_type: int = Field(description="资源类型")  # 使用group_resource.ResourceTypeEnum枚举值
    user_id: int = Field(default=0, description='创建用户ID')
    create_time: Optional[datetime] = Field(sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')), description="创建时间")
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=False,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')), description="更新时间")


class TagLink(TagLinkBase, table=True):
    __table_args__ = (UniqueConstraint('resource_id', 'resource_type', 'tag_id', name='resource_tag_uniq'),)
    id: Optional[int] = Field(index=True, primary_key=True, description="标签关联唯一ID")


class TagDao(Tag):

    @classmethod
    def search_tags(cls, keyword: str = None, page: int = 0, limit: int = 0) -> List[Tag]:
        """ 默认获取所有标签 可分页查找 """
        statement = select(Tag)
        if keyword:
            statement = statement.where(Tag.name.like(f'%{keyword}%'))
        if page and limit:
            statement = statement.offset((page - 1) * limit).limit(limit)

        with session_getter() as session:
            return session.exec(statement).all()

    @classmethod
    def count_tags(cls, keyword: str = None) -> int:
        """ 统计标签数量 """
        statement = select(func.count(Tag.id))
        if keyword:
            statement = statement.where(Tag.name.like(f'%{keyword}%'))
        with session_getter() as session:
            return session.scalar(statement)

    @classmethod
    def insert_tag(cls, data: Tag) -> Tag:
        """ 插入一条新的标签数据 """
        with session_getter() as session:
            session.add(data)
            session.commit()
            session.refresh(data)
            return data

    @classmethod
    def delete_tag(cls, tag_id: int) -> bool:
        """ 删除一条标签数据 """
        with session_getter() as session:
            # 删除标签数据
            session.exec(delete(Tag).where(Tag.id == tag_id))
            # 删除标签关联的数据
            session.exec(delete(TagLink).where(TagLink.tag_id == tag_id))
            session.commit()
            return True

    @classmethod
    def get_tag_by_name(cls, name: str) -> Tag:
        """ 通过标签名查找标签 """
        with session_getter() as session:
            statement = select(Tag).where(Tag.name == name)
            return session.exec(statement).first()

    @classmethod
    def get_tag_by_id(cls, tag_id: int) -> Tag:
        """ 通过标签ID查找标签 """
        with session_getter() as session:
            statement = select(Tag).where(Tag.id == tag_id)
            return session.exec(statement).first()

    @classmethod
    def get_tags_by_ids(cls, tag_ids: List[int]) -> List[Tag]:
        """ 通过标签ID查找标签 """
        with session_getter() as session:
            statement = select(Tag).where(Tag.id.in_(tag_ids))
            return session.exec(statement).all()

    @classmethod
    def get_tags_by_resource(cls, resource_type: ResourceTypeEnum, resource_ids: list[str]) -> Dict[str, List[Tag]]:
        """ 查询资源下的所有标签 """
        with session_getter() as session:
            statement = select(Tag.id, Tag.name, TagLink.resource_id).join(TagLink,
                                                                           and_(
                                                                               Tag.id == TagLink.tag_id,
                                                                               TagLink.resource_id.in_(resource_ids),
                                                                               TagLink.resource_type == resource_type.value))
            result = session.exec(statement).all()
            ret = {}
            for one in result:
                if one[2] not in ret:
                    ret[one[2]] = []
                ret[one[2]].append(Tag(id=one[0], name=one[1]))
            return ret

    @classmethod
    def get_resources_by_tags(cls, tag_ids: List[int], resource_type: ResourceTypeEnum) -> List[TagLink]:
        """ 查询标签下的所有资源 """

        statement = select(TagLink).where(TagLink.tag_id.in_(tag_ids), TagLink.resource_type == resource_type.value)
        with session_getter() as session:
            return session.exec(statement).all()

    @classmethod
    def insert_tag_link(cls, tag_link: TagLink) -> TagLink:
        """ 插入标签关联数据 """
        with session_getter() as session:
            session.add(tag_link)
            session.commit()
            session.refresh(tag_link)
            return tag_link

    @classmethod
    def get_tag_link(cls, tag_link_id: int) -> TagLink:
        """ 通过标签关联ID查找标签关联数据 """
        with session_getter() as session:
            statement = select(TagLink).where(TagLink.id == tag_link_id)
            return session.exec(statement).first()

    @classmethod
    def delete_tag_link(cls, tag_link_id: int) -> bool:
        """ 删除标签关联数据 """
        with session_getter() as session:
            # 删除标签关联数据
            session.exec(delete(TagLink).where(TagLink.id == tag_link_id))
            session.commit()
            return True

    @classmethod
    def delete_resource_tag(cls, tag_id: int, resource_id: str, resource_type: ResourceTypeEnum) -> bool:
        """ 删除标签关联数据 """
        statement = delete(TagLink).where(
            TagLink.tag_id == tag_id,
            TagLink.resource_id == resource_id,
            TagLink.resource_type == resource_type.value
        )
        with session_getter() as session:
            # 删除标签关联数据
            session.exec(statement)
            session.commit()
            return True
