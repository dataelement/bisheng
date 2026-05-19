import uuid
from datetime import datetime
from enum import Enum
from typing import Optional, Dict

from sqlalchemy import Enum as SQLEnum, DateTime, text
from sqlalchemy import CHAR, Column, Integer
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable


from bisheng.core.database.dialect_helpers import JsonType, UPDATE_TIME_SERVER_DEFAULT

class ResourceTypeEnum(str, Enum):
    """Resource Type Enumeration"""

    # Inspirational Sessions
    LINSIGHT_SESSION = "linsight_session"
    # Workbench Conversation
    WORKBENCH_CHAT = "workbench_chat"
    # The Workflow
    WORKFLOW = "workflow"
    # assistant
    ASSISTANT = "assistant"
    # Knowledge space file shared by Shougang portal
    KNOWLEDGE_SPACE_FILE = "knowledge_space_file"


class ShareMode(str, Enum):
    """Shared Mode Enumeration"""
    # Read-Only
    READ_ONLY = "read_only"
    # Can Edit
    EDITABLE = "editable"


class ShareLinkStatusEnum(str, Enum):
    """Shared link status enumeration"""
    # Effective
    ACTIVE = "active"
    # Tidak berlaku
    INACTIVE = "inactive"
    # Kedaluwarsa
    EXPIRED = "expired"


class ShareLink(SQLModelSerializable, table=True):
    """
    Shared Link Model
    """

    __tablename__ = 'share_link'

    id: str = Field(default_factory=lambda: uuid.uuid4().hex, description='Share linkID',
                    sa_column=Column(CHAR(36), unique=True, nullable=False, primary_key=True))
    share_token: str = Field(sa_column=Column(CHAR(36), index=True, unique=True), description='Share linkToken')

    resource_id: str = Field(sa_column=Column(CHAR(36), index=True), description='reasourseID')

    resource_type: ResourceTypeEnum = Field(..., sa_column=Column(SQLEnum(ResourceTypeEnum)), description='Resource Type')

    share_mode: ShareMode = Field(..., sa_column=Column(SQLEnum(ShareMode)), description='sharing mode')
    status: ShareLinkStatusEnum = Field(default=ShareLinkStatusEnum.ACTIVE,
                                        sa_column=Column(SQLEnum(ShareLinkStatusEnum)), description='Share link status')
    access_count: int = Field(default=0, description='Number of visits')
    meta_data: Optional[Dict] = Field(default=None, description='Shared link metadata', sa_column=Column(JsonType, nullable=True))
    expire_time: int = Field(default=0, description='Expiration time, in seconds,0Indicates never expires')

    create_user_id: str = Field(..., sa_column=Column(CHAR(36)), description='Create UserID')

    tenant_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, nullable=False, server_default=text('1'),
                         index=True, comment='Tenant ID'),
    )

    create_time: datetime = Field(default_factory=datetime.now, description='Creation Time',
                                  sa_column=Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))

    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=True, server_default=UPDATE_TIME_SERVER_DEFAULT))
