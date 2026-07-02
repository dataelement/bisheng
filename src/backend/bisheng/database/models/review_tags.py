from datetime import datetime
from enum import Enum

from pydantic import Field
from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint
from sqlmodel import Field, col, delete, select, text

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_async_db_session
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT
from bisheng.database.models.group_resource import ResourceTypeEnum

from .tag import TagBusinessTypeEnum, TagResourceTypeEnum


class ApproveOrRejectEnum(Enum):
    APPROVE = 1
    REJECT = 2


class ReviewTagBase(SQLModelSerializable):
    """
    Review Tag Form
    """

    name: str | None = Field(default=None, index=True, description="Label Name")
    business_type: str = Field(default=TagBusinessTypeEnum.APPLICATION, description="Business Type")
    business_id: str | None = Field(default=None, sa_column=Column(String(36)), description="Business ID")
    user_id: int = Field(default=0, description="Create UserID")
    tenant_id: int | None = Field(
        default=1,
        sa_column=Column(Integer, nullable=False, server_default=text("1"), index=True, comment="Tenant ID"),
    )
    resource_type: str = Field(default=TagResourceTypeEnum.MANUAL_TAG, description="Resource Type")
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, index=True, server_default=text("CURRENT_TIMESTAMP")),
        description="Creation Time",
    )
    update_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT)
    )


class ReviewTag(ReviewTagBase, table=True):
    __tablename__ = "review_tag"
    id: int | None = Field(default=None, index=True, primary_key=True, description="Tag UniqueID")
    is_deleted: bool = Field(default=False, description="Is Deleted")
    review_status: int = Field(default=0, description="Review Status")
    reject_reason: str | None = Field(default=None, sa_column=Column(String(256)), description="Reject Reason")
    review_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=True), description="Review Time"
    )
    remark: str | None = Field(default=None, sa_column=Column(String(256)), description="Remark")


class ReviewTagLinkBase(SQLModelSerializable):
    """
    Review Tag Association Table
    """

    tag_id: int = Field(index=True, description="labelID")
    resource_id: str = Field(description="Resource UniqueID")
    resource_type: int = Field(description="Resource Type")  # Usegroup_resource.ResourceTypeEnumEnumeration
    user_id: int = Field(default=0, description="Create UserID")
    tenant_id: int | None = Field(
        default=1,
        sa_column=Column(Integer, nullable=False, server_default=text("1"), index=True, comment="Tenant ID"),
    )
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, index=True, server_default=text("CURRENT_TIMESTAMP")),
        description="Creation Time",
    )
    update_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT)
    )


class ReviewTagLink(ReviewTagLinkBase, table=True):
    __tablename__ = "review_tag_link"
    __table_args__ = (UniqueConstraint("resource_id", "resource_type", "tag_id", name="resource_tag_uniq"),)
    id: int | None = Field(default=None, index=True, primary_key=True, description="Tag Association UniqueID")
    is_deleted: bool = Field(default=False, description="Is Deleted")
    remark: str | None = Field(default=None, sa_column=Column(String(256)), description="Remark")


class ReviewTagDao(ReviewTag):
    @classmethod
    async def get_tags_by_business(
        cls, business_type: TagBusinessTypeEnum, business_id: str, name: str = None
    ) -> list[ReviewTag]:
        statement = select(ReviewTag).where(
            ReviewTag.business_type == business_type, ReviewTag.business_id == business_id
        )
        if name:
            statement = statement.where(ReviewTag.name == name)
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    async def ainsert_review_tag(cls, data: ReviewTag) -> ReviewTag:
        """Insert a new review tag data"""
        async with get_async_db_session() as session:
            session.add(data)
            await session.commit()
            await session.refresh(data)
            return data

    @classmethod
    async def aupdate_resource_tags(
        cls,
        tag_ids: list[int],
        resource_id: str,
        resource_type: ResourceTypeEnum,
        user_id: int,
        tenant_id: int | None = None,
    ) -> bool:
        """Update tag association data"""
        async with get_async_db_session() as session:
            # Delete original tag association data
            statement = delete(ReviewTagLink).where(
                col(ReviewTagLink.resource_id) == resource_id, col(ReviewTagLink.resource_type) == resource_type.value
            )
            await session.exec(statement)
            # Insert new tag association data
            for tag_id in tag_ids:
                tag_link = ReviewTagLink(
                    tag_id=tag_id,
                    resource_id=resource_id,
                    resource_type=resource_type.value,
                    user_id=user_id,
                    tenant_id=tenant_id,
                    is_deleted=False,
                )
                session.add(tag_link)
            await session.commit()
            return True

    @classmethod
    async def add_tags(
        cls,
        review_tag_ids: list[int],
        resource_id: str,
        resource_type: ResourceTypeEnum,
        user_id: int,
        tenant_id: int | None = None,
    ) -> bool:
        """Add tag association data"""
        exists_statement = select(ReviewTagLink).where(
            ReviewTagLink.resource_id == resource_id,
            ReviewTagLink.resource_type == resource_type.value,
        )
        async with get_async_db_session() as session:
            exists_tags = (await session.exec(exists_statement)).all()
            need_add_tags = set(review_tag_ids) - set([one.tag_id for one in exists_tags])
            for one in need_add_tags:
                session.add(
                    ReviewTagLink(
                        tag_id=one,
                        resource_id=resource_id,
                        resource_type=resource_type.value,
                        user_id=user_id,
                        tenant_id=tenant_id,
                        is_deleted=False,
                    )
                )
            await session.commit()
            return True
