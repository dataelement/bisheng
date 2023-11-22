from datetime import datetime
from typing import Dict, Optional
from uuid import UUID

from bisheng.database.models.base import SQLModelSerializable
from pydantic import BaseModel
from sqlalchemy import JSON, Column, DateTime, Text, text
from sqlmodel import Field


class MessageBase(SQLModelSerializable):
    is_bot: bool = Field(index=False, description='聊天角色')
    source: Optional[bool] = Field(index=False, description='是否支持溯源')
    message: Optional[str] = Field(index=False, sa_column=Column(Text), description='聊天消息')
    type: str = Field(index=False, description='消息类型')
    category: str = Field(index=False, description='消息类别， question等')
    flow_id: UUID = Field(index=True, description='对应的技能id')
    chat_id: Optional[str] = Field(index=True, description='chat_id, 前端生成')
    user_id: Optional[str] = Field(index=True, description='用户id')
    sender: Optional[str] = Field(index=False, default='', description='autogen 的发送方')
    receiver: Optional[Dict] = Field(index=False, default=None, description='autogen 的发送方')
    intermediate_steps: Optional[str] = Field(index=False,
                                              sa_column=Column(Text),
                                              description='过程日志')
    files: Optional[str] = Field(index=False, description='上传的文件等')
    # file_access: Optional[bool] = Field(index=False, default=True, description='召回文件是否可以访问')
    create_time: Optional[datetime] = Field(
        sa_column=Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(index=True,
                                            sa_column=Column(
                                                DateTime,
                                                nullable=False,
                                                index=True,
                                                server_default=text('CURRENT_TIMESTAMP'),
                                                onupdate=text('CURRENT_TIMESTAMP')))


class ChatMessage(MessageBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    receiver: Optional[Dict] = Field(default=None, sa_column=Column(JSON))


class ChatMessageRead(MessageBase):
    id: Optional[int]


class ChatMessageQuery(BaseModel):
    id: Optional[int]
    flow_id: str
    chat_id: str


class ChatMessageCreate(MessageBase):
    pass
