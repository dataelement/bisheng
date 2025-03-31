from datetime import datetime
from enum import Enum
from typing import Optional, List

from sqlmodel import Field, Column, DateTime, text, select, update

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable


class ReviewStatus(Enum):
    DEFAULT = 1  # 未审查
    PASS = 2  # 通过
    VIOLATIONS = 3  # 违规
    FAILED = 4  # 审查失败


class MessageSessionBase(SQLModelSerializable):
    """ 会话列表表 TODO 目前只存储了审查后的会话，后续将会话数据全部迁移过来"""
    chat_id: str = Field(default=None, primary_key=True, description='会话唯一ID')
    flow_id: str = Field(index=True, description='应用唯一ID')
    flow_type: int = Field(description='应用类型。技能、助手、工作流')
    flow_name: str = Field(description='应用名称')
    user_id: int = Field(description='创建会话的用户ID')
    like: Optional[int] = Field(default=0, description='点赞的消息数量')
    dislike: Optional[int] = Field(default=0, description='点踩的消息数量')
    copied: Optional[int] = Field(default=0, description='已复制的消息数量')
    review_status: int = Field(default=ReviewStatus.DEFAULT.value, description='审查状态')
    create_time: Optional[datetime] = Field(
        sa_column=Column(DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')))


class MessageSession(MessageSessionBase, table=True):
    __tablename__ = 'message_session'


class MessageSessionDao(MessageSessionBase):

    @classmethod
    def insert_one(cls, data: MessageSession) -> MessageSession:
        with session_getter() as session:
            session.add(data)
            session.commit()
            session.refresh(data)
            return data

    @classmethod
    def delete_session(cls, chat_id: str):
        statement = update(MessageSession).where(MessageSession.chat_id == chat_id).values(is_delete=True)
        with session_getter() as session:
            session.exec(statement)
            session.commit()

    @classmethod
    def get_one(cls, chat_id: str) -> MessageSession | None:
        statement = select(MessageSession).where(MessageSession.chat_id == chat_id)
        with session_getter() as session:
            return session.exec(statement).first()

    @classmethod
    def filter_session(cls, chat_ids: List[str] = None, review_status: List[int] = None) -> List[MessageSession]:
        statement = select(MessageSession)
        if chat_ids:
            statement = statement.where(MessageSession.chat_id.in_(chat_ids))
        if review_status:
            statement = statement.where(MessageSession.review_status.in_(review_status))
        with session_getter() as session:
            return session.exec(statement).all()
