from datetime import datetime
from typing import Optional, List, Dict

from sqlalchemy import Column, DateTime, UniqueConstraint
from sqlmodel import Field, select, delete, and_, func, text

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_sync_db_session
from bisheng.database.models.group_resource import ResourceTypeEnum


class TagBase(SQLModelSerializable):
    """
    Tag Form
    """
    name: Optional[str] = Field(default=None, index=True, unique=True, description="Label Name")
    user_id: int = Field(default=0, description='Create UserID')
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')), description="Creation Time")
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))


class Tag(TagBase, table=True):
    id: Optional[int] = Field(default=None, index=True, primary_key=True, description="Tag UniqueID")


class TagLinkBase(SQLModelSerializable):
    """
    Label Association Table
    """
    tag_id: int = Field(index=True, description="labelID")
    resource_id: str = Field(description="Resource UniqueID")
    resource_type: int = Field(description="Resource Type")  # Usegroup_resource.ResourceTypeEnumEnumeration
    user_id: int = Field(default=0, description='Create UserID')
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')), description="Creation Time")
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))


class TagLink(TagLinkBase, table=True):
    __table_args__ = (UniqueConstraint('resource_id', 'resource_type', 'tag_id', name='resource_tag_uniq'),)
    id: Optional[int] = Field(default=None, index=True, primary_key=True, description="Tag Association UniqueID")


class TagDao(Tag):

    @classmethod
    def search_tags(cls, keyword: str = None, page: int = 0, limit: int = 0) -> List[Tag]:
        """ Get all tags by default Paginable """
        statement = select(Tag)
        if keyword:
            statement = statement.where(Tag.name.like(f'%{keyword}%'))
        if page and limit:
            statement = statement.offset((page - 1) * limit).limit(limit)

        with get_sync_db_session() as session:
            return session.exec(statement).all()

    @classmethod
    def count_tags(cls, keyword: str = None) -> int:
        """ Count the number of tags """
        statement = select(func.count(Tag.id))
        if keyword:
            statement = statement.where(Tag.name.like(f'%{keyword}%'))
        with get_sync_db_session() as session:
            return session.scalar(statement)

    @classmethod
    def insert_tag(cls, data: Tag) -> Tag:
        """ Insert a new label data """
        with get_sync_db_session() as session:
            session.add(data)
            session.commit()
            session.refresh(data)
            return data

    @classmethod
    def delete_tag(cls, tag_id: int) -> bool:
        """ Delete a label data """
        with get_sync_db_session() as session:
            # Delete tag data
            session.exec(delete(Tag).where(Tag.id == tag_id))
            # Delete data associated with tags
            session.exec(delete(TagLink).where(TagLink.tag_id == tag_id))
            session.commit()
            return True

    @classmethod
    def get_tag_by_name(cls, name: str) -> Tag:
        """ Find tags by tag name """
        with get_sync_db_session() as session:
            statement = select(Tag).where(Tag.name == name)
            return session.exec(statement).first()

    @classmethod
    def get_tag_by_id(cls, tag_id: int) -> Tag:
        """ by TagIDFind Tags """
        with get_sync_db_session() as session:
            statement = select(Tag).where(Tag.id == tag_id)
            return session.exec(statement).first()

    @classmethod
    def get_tags_by_ids(cls, tag_ids: List[int]) -> List[Tag]:
        """ by TagIDFind Tags """
        with get_sync_db_session() as session:
            statement = select(Tag).where(Tag.id.in_(tag_ids))
            return session.exec(statement).all()

    @classmethod
    def get_tags_by_resource(cls, resource_type: ResourceTypeEnum | None, resource_ids: list[str]) -> Dict[
        str, List[Tag]]:
        """ Query all tags under resources """
        if resource_type is None:
            statement = select(Tag.id, Tag.name, TagLink.resource_id).join(TagLink,
                                                                           and_(
                                                                               Tag.id == TagLink.tag_id,
                                                                               TagLink.resource_id.in_(resource_ids)))
        else:
            statement = select(Tag.id, Tag.name, TagLink.resource_id).join(TagLink,
                                                                           and_(
                                                                               Tag.id == TagLink.tag_id,
                                                                               TagLink.resource_id.in_(resource_ids),
                                                                               TagLink.resource_type == resource_type.value))
        with get_sync_db_session() as session:
            result = session.exec(statement).all()
        ret = {}
        for one in result:
            if one[2] not in ret:
                ret[one[2]] = []
            ret[one[2]].append(Tag(id=one[0], name=one[1]))
        return ret

    @classmethod
    def get_tags_by_resource_batch(cls, resource_type: List[ResourceTypeEnum], resource_ids: list[str]) -> Dict[
        str, List[Tag]]:
        """ Query all tags under resources """
        with get_sync_db_session() as session:
            statement = select(Tag.id, Tag.name, TagLink.resource_id).join(TagLink,
                                                                           and_(
                                                                               Tag.id == TagLink.tag_id,
                                                                               TagLink.resource_id.in_(resource_ids),
                                                                               TagLink.resource_type.in_(
                                                                                   [x.value for x in resource_type])))
            result = session.exec(statement).all()
            ret = {}
            for one in result:
                if one[2] not in ret:
                    ret[one[2]] = []
                ret[one[2]].append(Tag(id=one[0], name=one[1]))
            return ret

    @classmethod
    def get_resources_by_tags(cls, tag_ids: List[int], resource_type: ResourceTypeEnum) -> List[TagLink]:
        """ Query all resources under tags """

        statement = select(TagLink).where(TagLink.tag_id.in_(tag_ids), TagLink.resource_type == resource_type.value)
        with get_sync_db_session() as session:
            return session.exec(statement).all()

    @classmethod
    def get_resources_by_tags_batch(cls, tag_ids: List[int], resource_type: List[ResourceTypeEnum]) -> List[TagLink]:
        """ Query all resources under tags """

        statement = select(TagLink).where(TagLink.tag_id.in_(tag_ids),
                                          TagLink.resource_type.in_([x.value for x in resource_type]))
        with get_sync_db_session() as session:
            return session.exec(statement).all()

    @classmethod
    def insert_tag_link(cls, tag_link: TagLink) -> TagLink:
        """ Insert Label Associated Data """
        with get_sync_db_session() as session:
            session.add(tag_link)
            session.commit()
            session.refresh(tag_link)
            return tag_link

    @classmethod
    def get_tag_link(cls, tag_link_id: int) -> TagLink:
        """ Associate via tagsIDFind Label Associated Data """
        with get_sync_db_session() as session:
            statement = select(TagLink).where(TagLink.id == tag_link_id)
            return session.exec(statement).first()

    @classmethod
    def delete_tag_link(cls, tag_link_id: int) -> bool:
        """ Delete tag association data """
        with get_sync_db_session() as session:
            # Delete tag association data
            session.exec(delete(TagLink).where(TagLink.id == tag_link_id))
            session.commit()
            return True

    @classmethod
    def delete_resource_tag(cls, tag_id: int, resource_id: str, resource_type: ResourceTypeEnum) -> bool:
        """ Delete tag association data """
        statement = delete(TagLink).where(
            TagLink.tag_id == tag_id,
            TagLink.resource_id == resource_id,
            TagLink.resource_type == resource_type.value
        )
        with get_sync_db_session() as session:
            # Delete tag association data
            session.exec(statement)
            session.commit()
            return True
