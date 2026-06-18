from datetime import datetime
from sqlalchemy import Column, DateTime, String
from pydantic import Field
from typing import Optional
from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict

from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint
from sqlmodel import Field, select, delete, and_, func, text, col

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_sync_db_session, get_async_db_session
from bisheng.database.models.group_resource import ResourceTypeEnum
from .tag import TagBusinessTypeEnum, TagResourceTypeEnum

from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT

class ApproveOrRejectEnum(Enum):
    APPROVE = 1
    REJECT = 2


class ReviewTagBase(SQLModelSerializable):
    """
    Review Tag Form
    """
    name: Optional[str] = Field(default=None, index=True, description="Label Name")
    business_type: str = Field(default=TagBusinessTypeEnum.APPLICATION, description="Business Type")
    business_id: Optional[str] = Field(default=None, sa_column=Column(String(36)), description="Business ID")
    user_id: int = Field(default=0, description='Create UserID')
    tenant_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, nullable=False, server_default=text('1'),
                         index=True, comment='Tenant ID'),
    )
    resource_type: str = Field(default=TagResourceTypeEnum.MANUAL_TAG, description="Resource Type")
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')), description="Creation Time")
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT))

class ReviewTag(ReviewTagBase, table=True):
    __tablename__ = 'review_tag'
    id: Optional[int] = Field(default=None, index=True, primary_key=True, description="Tag UniqueID")
    is_deleted: bool = Field(default=False, description="Is Deleted")
    review_status: int = Field(default=0, description="Review Status")
    reject_reason: Optional[str] = Field(default=None, sa_column=Column(String(256)), description="Reject Reason")
    review_time: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True), description="Review Time")
    remark: Optional[str] = Field(default=None, sa_column=Column(String(256)), description="Remark")


class ReviewTagLinkBase(SQLModelSerializable):
    """
    Review Tag Association Table
    """
    tag_id: int = Field(index=True, description="labelID")
    resource_id: str = Field(description="Resource UniqueID")
    resource_type: int = Field(description="Resource Type")  # Usegroup_resource.ResourceTypeEnumEnumeration
    user_id: int = Field(default=0, description='Create UserID')
    tenant_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, nullable=False, server_default=text('1'),
                         index=True, comment='Tenant ID'),
    )
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')), description="Creation Time")
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT))


class ReviewTagLink(ReviewTagLinkBase, table=True):
    __tablename__ = 'review_tag_link'
    id: Optional[int] = Field(default=None, index=True, primary_key=True, description="Tag Association UniqueID")
    is_deleted: bool = Field(default=False, description="Is Deleted")
    remark: Optional[str] = Field(default=None, sa_column=Column(String(256)), description="Remark")


class ReviewTagDao(ReviewTag):
    pass
