from datetime import datetime
from typing import Optional
from uuid import UUID

from bisheng.database.models.base import SQLModelSerializable
from pydantic import BaseModel
from sqlalchemy import Column, DateTime, String, Text, text
from sqlmodel import Field


class MessageBase(SQLModelSerializable):
    is_bot: bool = Field(index=False)
    message: Optional[str] = Field(index=False, sa_column=Column(Text))
    type: str = Field(index=False)
    category: str = Field(index=False)
    flow_id: UUID = Field(index=True)
    chat_id: Optional[str] = Field(index=True)
    user_id: Optional[str] = Field(index=True)
    intermediate_steps: Optional[str] = Field(
        index=False, sa_column=Column(String(length=1024))
    )
    files: Optional[str] = Field(index=False)
    create_time: Optional[datetime] = Field(
        sa_column=Column(
            DateTime,
            nullable=False,
            index=True,
            server_default=text('CURRENT_TIMESTAMP')
        )
    )
    update_time: Optional[datetime] = Field(
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=text('CURRENT_TIMESTAMP'),
            onupdate=text('CURRENT_TIMESTAMP')
        )
    )


class ChatMessage(MessageBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)


class ChatMessageRead(MessageBase):
    id: Optional[int]


class ChatMessageQuery(BaseModel):
    id: Optional[int]
    flow_id: str
    chat_id: str


class ChatMessageCreate(MessageBase):
    pass
