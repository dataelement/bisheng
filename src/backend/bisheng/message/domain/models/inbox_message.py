from datetime import datetime
from enum import Enum
from typing import List, Optional, Any

from sqlalchemy import Column, Integer, JSON, DateTime, text, Enum as SQLEnum
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable


class MessageTypeEnum(str, Enum):
    """Message Type Enumeration"""
    NOTIFY = "notify"
    APPROVE = "approve"


class MessageStatusEnum(str, Enum):
    """Message Status Enumeration"""
    WAIT_APPROVE = "wait_approve"
    APPROVED = "approved"
    REJECTED = "rejected"


class InboxMessage(SQLModelSerializable, table=True):
    """
    Inbox Message Model - stores in-app notification and approval messages.
    """

    __tablename__ = 'inbox_message'

    id: Optional[int] = Field(
        default=None,
        description='Message ID',
        sa_column=Column(Integer, primary_key=True, autoincrement=True)
    )
    content: List[Any] = Field(
        default_factory=list,
        description='Message content in JSON array format',
        sa_column=Column(JSON, nullable=False)
    )
    sender: int = Field(
        ...,
        description='Sender user ID',
        nullable=False
    )
    message_type: MessageTypeEnum = Field(
        ...,
        description='Message type: notify or approve',
        sa_column=Column(SQLEnum(MessageTypeEnum), nullable=False, index=True)
    )
    receiver: List[int] = Field(
        default_factory=list,
        description='Receiver user ID list',
        sa_column=Column(JSON, nullable=False)
    )
    status: MessageStatusEnum = Field(
        default=MessageStatusEnum.WAIT_APPROVE,
        description='Message status: wait_approve, approved, rejected',
        sa_column=Column(SQLEnum(MessageStatusEnum), nullable=False, index=True)
    )

    create_time: datetime = Field(
        default_factory=datetime.now,
        description='Creation time',
        sa_column=Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP'))
    )
    update_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            DateTime, nullable=True,
            server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')
        )
    )
