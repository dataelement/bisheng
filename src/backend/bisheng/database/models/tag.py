from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict

from sqlalchemy import Column, DateTime, String, UniqueConstraint
from sqlmodel import Field, select, delete, and_, func, text, col

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_sync_db_session, get_async_db_session
from bisheng.database.models.group_resource import ResourceTypeEnum


class TagBusinessTypeEnum(str, Enum):
    KNOWLEDGE_SPACE = 'knowledge_space'
    APPLICATION = 'application'
    KNOWLEDGE = 'knowledge'


class TagBase(SQLModelSerializable):
    """
    Tag Form
    """
    name: Optional[str] = Field(default=None, index=True, description="Label Name")
    business_type: str = Field(default=TagBusinessTypeEnum.APPLICATION, description="Business Type")
    business_id: Optional[str] = Field(default=None, sa_column=Column(String(36)), description="Business ID")
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
    def search_tags(cls, keyword: str = None, page: int = 0, limit: int = 0, *,
                    business_type: TagBusinessTypeEnum, business_id: str) -> List[Tag]:
        """ Get all tags by default Paginable """
        statement = select(Tag)
        if keyword:
            statement = statement.where(Tag.name.like(f'%{keyword}%'))
        if page and limit:
            statement = statement.offset((page - 1) * limit).limit(limit)
        statement = statement.where(Tag.business_type == business_type,
                                    Tag.business_id == business_id)

        with get_sync_db_session() as session:
            return session.exec(statement).all()

    @classmethod
    def count_tags(cls, keyword: str = None, *, business_type: TagBusinessTypeEnum, business_id: str) -> int:
        """ Count the number of tags """
        statement = select(func.count(Tag.id))
        if keyword:
            statement = statement.where(Tag.name.like(f'%{keyword}%'))
        statement = statement.where(Tag.business_type == business_type,
                                    Tag.business_id == business_id)
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
    async def ainsert_tag(cls, data: Tag) -> Tag:
        """ Insert a new label data """
        async with get_async_db_session() as session:
            session.add(data)
            await session.commit()
            await session.refresh(data)
            return data

    @classmethod
    async def get_tag(cls, tag_id: int) -> Optional[Tag]:
        """Find a tag by id asynchronously."""
        statement = select(Tag).where(Tag.id == tag_id)
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.first()

    @classmethod
    def update_tag(cls, data: Tag) -> Tag:
        """ Update a new label data """
        if data.id is None:
            raise ValueError("Tag ID cannot be None for update operation")

        with get_sync_db_session() as session:
            session.add(data)
            session.commit()
            session.refresh(data)
            return data

    @classmethod
    async def aupdate_tag(cls, tag_id: int, **kwargs) -> Tag:
        """Update a tag asynchronously."""
        async with get_async_db_session() as session:
            statement = select(Tag).where(Tag.id == tag_id)
            result = await session.exec(statement)
            data = result.first()
            if data is None:
                raise ValueError("Tag does not exist")

            for key, value in kwargs.items():
                setattr(data, key, value)

            session.add(data)
            await session.commit()
            await session.refresh(data)
            return data

    @classmethod
    def delete_tag(cls, tag_id: int) -> bool:
        """ Delete a label data """
        with get_sync_db_session() as session:
            # Delete tag data
            session.exec(delete(Tag).where(col(Tag.id) == tag_id))
            # Delete data associated with tags
            session.exec(delete(TagLink).where(col(TagLink.tag_id) == tag_id))
            session.commit()
            return True

    @classmethod
    async def delete_business_tag(cls, tag_id: int, business_type: TagBusinessTypeEnum, business_id: str) -> bool:
        """ Delete a label data """
        statement = delete(Tag).where(col(Tag.business_type) == business_type,
                                      col(Tag.business_id) == business_id,
                                      col(Tag.id) == tag_id)
        async with get_async_db_session() as session:
            await session.exec(statement)
            await session.commit()
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
    async def aget_tags_by_ids(cls, tag_ids: List[int]) -> List[Tag]:
        """Find tags by ids asynchronously."""
        if not tag_ids:
            return []
        statement = select(Tag).where(Tag.id.in_(tag_ids))
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    async def get_tags_by_business(cls, business_type: TagBusinessTypeEnum, business_id: str, name: str = None) -> List[
        Tag]:
        statement = select(Tag).where(Tag.business_type == business_type, Tag.business_id == business_id)
        if name:
            statement = statement.where(Tag.name == name)
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    async def asearch_tags(
            cls,
            keyword: str = None,
            page: int = 1,
            limit: int = 10,
            *,
            business_type: TagBusinessTypeEnum,
            business_id: str,
    ) -> List[Tag]:
        """Search tags by business scope asynchronously."""
        statement = select(Tag).where(
            Tag.business_type == business_type,
            Tag.business_id == business_id,
        )
        if keyword:
            statement = statement.where(Tag.name.like(f'%{keyword}%'))
        statement = statement.order_by(Tag.id.desc())
        if page > 0 and limit > 0:
            statement = statement.offset((page - 1) * limit).limit(limit)

        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    async def acount_tags(
            cls,
            keyword: str = None,
            *,
            business_type: TagBusinessTypeEnum,
            business_id: str,
    ) -> int:
        """Count tags by business scope asynchronously."""
        statement = select(func.count(Tag.id)).where(
            Tag.business_type == business_type,
            Tag.business_id == business_id,
        )
        if keyword:
            statement = statement.where(Tag.name.like(f'%{keyword}%'))

        async with get_async_db_session() as session:
            return await session.scalar(statement)

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
    async def aget_resources_by_tags(cls, tag_ids: List[int], resource_type: ResourceTypeEnum) -> List[TagLink]:
        """ Query all resources under tags """
        statement = select(TagLink).where(TagLink.tag_id.in_(tag_ids), TagLink.resource_type == resource_type.value)
        async with get_async_db_session() as session:
            return (await session.exec(statement)).all()

    @classmethod
    async def aget_resource_tag_ids_batch(
            cls, resource_ids: List[str], resource_type: ResourceTypeEnum
    ) -> Dict[str, List[int]]:
        """Query tag ids grouped by resource id asynchronously."""
        if not resource_ids:
            return {}

        statement = select(TagLink.resource_id, TagLink.tag_id).where(
            TagLink.resource_id.in_(resource_ids),
            TagLink.resource_type == resource_type.value,
        )
        async with get_async_db_session() as session:
            rows = (await session.exec(statement)).all()

        result: Dict[str, List[int]] = {}
        for resource_id, tag_id in rows:
            result.setdefault(resource_id, []).append(tag_id)
        return result

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

    @classmethod
    async def aupdate_resource_tags(cls, tag_ids: List[int], resource_id: str, resource_type: ResourceTypeEnum,
                                    user_id: int) -> bool:
        """ Update tag association data """
        async with get_async_db_session() as session:
            # Delete original tag association data
            statement = delete(TagLink).where(
                col(TagLink.resource_id) == resource_id,
                col(TagLink.resource_type) == resource_type.value
            )
            await session.exec(statement)
            # Insert new tag association data
            for tag_id in tag_ids:
                tag_link = TagLink(tag_id=tag_id, resource_id=resource_id, resource_type=resource_type.value,
                                   user_id=user_id)
                session.add(tag_link)
            await session.commit()
            return True

    @classmethod
    async def add_tags(cls, tag_ids: List[int], resource_id: str, resource_type: ResourceTypeEnum,
                       user_id: int) -> bool:
        """ Add tag association data """
        exists_statement = select(TagLink).where(
            TagLink.resource_id == resource_id,
            TagLink.resource_type == resource_type.value,
        )
        async with get_async_db_session() as session:
            exists_tags = (await session.exec(exists_statement)).all()
            need_add_tags = set(tag_ids) - set([one.tag_id for one in exists_tags])
            for one in need_add_tags:
                session.add(
                    TagLink(tag_id=one, resource_id=resource_id, resource_type=resource_type.value, user_id=user_id))
            await session.commit()
            return True
