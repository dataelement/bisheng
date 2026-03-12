from datetime import datetime
from typing import Optional

from sqlalchemy import Column, Integer, DateTime, text, Index
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable


class InboxMessageRead(SQLModelSerializable, table=True):
    """
    Inbox Message Read Record Model - tracks which users have read which messages.
    """

    __tablename__ = 'inbox_message_read'

    __table_args__ = (
        Index('ix_inbox_message_read_msg_user', 'message_id', 'user_id', unique=True),
    )

    id: Optional[int] = Field(
        default=None,
        description='Record ID',
        sa_column=Column(Integer, primary_key=True, autoincrement=True)
    )
    message_id: int = Field(
        ...,
        description='Message ID',
        nullable=False,
        index=True
    )
    user_id: int = Field(
        ...,
        description='User ID',
        nullable=False,
        index=True
    )
    create_time: datetime = Field(
        default_factory=datetime.now,
        description='Read time',
        sa_column=Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP'))
    )
