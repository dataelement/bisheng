from datetime import datetime
from typing import Dict, Optional
from uuid import UUID

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import JSON, Column, DateTime, String, Text, func, text
from sqlmodel import Field, delete, select


class MessageBase(SQLModelSerializable):
    is_bot: bool = Field(index=False, description='聊天角色')
    source: Optional[int] = Field(index=False, description='是否支持溯源')
    message: Optional[str] = Field(sa_column=Column(Text), description='聊天消息')
    extra: Optional[str] = Field(sa_column=Column(String(length=4096)), description='连接信息等')
    type: str = Field(index=False, description='消息类型')
    category: str = Field(index=False, description='消息类别， question等')
    flow_id: UUID = Field(index=True, description='对应的技能id')
    chat_id: Optional[str] = Field(index=True, description='chat_id, 前端生成')
    user_id: Optional[str] = Field(index=True, description='用户id')
    liked: Optional[int] = Field(index=False, default=0, description='用户是否喜欢 0未评价/1 喜欢/2 不喜欢')
    solved: Optional[int] = Field(index=False, default=0, description='用户是否喜欢 0未评价/1 解决/2 未解决')
    sender: Optional[str] = Field(index=False, default='', description='autogen 的发送方')
    receiver: Optional[Dict] = Field(index=False, default=None, description='autogen 的发送方')
    intermediate_steps: Optional[str] = Field(sa_column=Column(Text), description='过程日志')
    files: Optional[str] = Field(sa_column=Column(String(length=4096)), description='上传的文件等')
    remark: Optional[str] = Field(sa_column=Column(String(length=4096)), description='备注')
    create_time: Optional[datetime] = Field(
        sa_column=Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
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


class MessageDao(MessageBase):

    @classmethod
    def static_msg_liked(cls, liked: int, flow_id: str, create_time_begin: datetime,
                         create_time_end: datetime):
        base_condition = select(func.count(ChatMessage.id)).where(ChatMessage.liked == liked)

        if flow_id:
            base_condition = base_condition.where(ChatMessage.flow_id == flow_id)

        if create_time_begin and create_time_end:
            base_condition = base_condition.where(ChatMessage.create_time > create_time_begin,
                                                  ChatMessage.create_time < create_time_end)

        with session_getter() as session:
            return session.scalar(base_condition)


class ChatMessageDao(MessageBase):

    @classmethod
    def get_latest_message_by_chatid(cls, chat_id: str):
        with session_getter() as session:
            res = session.exec(
                select(ChatMessage).where(ChatMessage.chat_id == chat_id).limit(1)).all()
            if res:
                return res[0]
            else:
                return None

    @classmethod
    def get_messages_by_chat_id(cls, chat_id: str, category_list: list = None, limit: int = 10):
        with session_getter() as session:
            statement = select(ChatMessage).where(ChatMessage.chat_id == chat_id)
            if category_list:
                statement = statement.where(ChatMessage.category.in_(category_list))
            statement = statement.limit(limit).order_by(ChatMessage.create_time.asc())
            return session.exec(statement).all()

    @classmethod
    def delete_by_user_chat_id(cls, user_id: int, chat_id: str):
        if user_id is None or chat_id is None:
            logger.info('delete_param_error user_id={} chat_id={}', user_id, chat_id)
            return False

        statement = delete(ChatMessage).where(ChatMessage.chat_id == chat_id,
                                              ChatMessage.user_id == user_id)

        with session_getter() as session:
            session.exec(statement)
            session.commit()
        return True

    @classmethod
    def delete_by_message_id(cls, user_id: int, message_id: str):
        if user_id is None or message_id is None:
            logger.info('delete_param_error user_id={} chat_id={}', user_id, message_id)
            return False

        statement = delete(ChatMessage).where(ChatMessage.id == message_id,
                                              ChatMessage.user_id == user_id)

        with session_getter() as session:
            session.exec(statement)
            session.commit()
        return True

    @classmethod
    def insert_one(cls, message: ChatMessage) -> ChatMessage:
        with session_getter() as session:
            session.add(message)
            session.commit()
            session.refresh(message)
        return message
