from datetime import datetime
from enum import Enum
from typing import Optional, List

from pydantic import validator
from sqlalchemy.dialects import mysql
from sqlmodel import Field, Column, DateTime, text, select, update, func

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable
from bisheng.database.models.user_group import UserGroup


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
    is_delete: Optional[bool] = Field(default=False, description='会话本身是否被删除')
    create_time: Optional[datetime] = Field(
        sa_column=Column(DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')))

    @validator("flow_id",pre=True)
    @classmethod
    def handle_flow_id(cls, v: str):
        return v.replace('-','')


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
    def generate_filter_session_statement(cls, statement, chat_ids: List[str] = None,
                                          review_status: List[ReviewStatus] = None,
                                          flow_ids: List[str] = None, user_ids: List[int] = None, feedback: str = None,
                                          start_date: datetime = None, end_date: datetime = None,
                                          include_delete: bool = True, exclude_chats: List[str] = None):
        if chat_ids:
            statement = statement.where(MessageSession.chat_id.in_(chat_ids))
        if flow_ids:
            statement = statement.where(MessageSession.flow_id.in_(flow_ids))
        if user_ids:
            statement = statement.where(MessageSession.user_id.in_(user_ids))

        if feedback == 'like':
            statement = statement.where(MessageSession.like > 0)
        elif feedback == 'dislike':
            statement = statement.where(MessageSession.dislike > 0)
        elif feedback == 'copied':
            statement = statement.where(MessageSession.copied > 0)

        if not include_delete:
            statement = statement.where(MessageSession.is_delete == False)
        if exclude_chats:
            statement = statement.where(MessageSession.chat_id.not_in(exclude_chats))
        if start_date:
            statement = statement.where(MessageSession.update_time >= start_date)
        if end_date:
            statement = statement.where(MessageSession.create_time <= end_date)
        if review_status:
            statement = statement.where(MessageSession.review_status.in_([one.value for one in review_status]))
        return statement

    @classmethod
    def get_user_flow(cls,user_ids: list[int]) -> Optional[int]:
        statement = select(func.distinct(MessageSession.flow_id)).where(MessageSession.user_id.in_(user_ids))
        with session_getter() as session:
            return session.exec(statement).all()

    @classmethod
    def get_flow_group_like_num(cls, flow_ids: list[str], user_ids: list[str]):
        # 构建查询语句，明确指定连接条件
        statement = select(
            MessageSession.flow_id,
            UserGroup.group_id,
            func.sum(MessageSession.like).label('likes'),
            func.sum(MessageSession.dislike).label('dislikes')
        ).select_from(MessageSession).join(
            UserGroup, MessageSession.user_id == UserGroup.user_id
        )
        if flow_ids:
            statement = statement.where(MessageSession.flow_id.in_(flow_ids))
        if user_ids:
            statement = statement.where(MessageSession.user_id.in_(user_ids))
        statement = statement.group_by(UserGroup.group_id,MessageSession.flow_id)
        with session_getter() as session:
            data = session.exec(statement).all()
        result = []
        for one in data:
            result.append({
                "flow_id":one[0],
                "group_id":one[1],
                "likes":one[2],
                "dislikes":one[3]
            })
        return result

    @classmethod
    def filter_session(cls, chat_ids: List[str] = None, review_status: List[ReviewStatus] = None,
                       flow_ids: List[str] = None, user_ids: List[int] = None, feedback: str = None,
                       start_date: datetime = None, end_date: datetime = None, include_delete: bool = True,
                       exclude_chats: List[str] = None, page: int = 0, limit: int = 0) -> List[MessageSession]:
        statement = select(MessageSession)
        statement = cls.generate_filter_session_statement(statement, chat_ids, review_status, flow_ids, user_ids,
                                                          feedback, start_date, end_date, include_delete, exclude_chats)
        if page and limit:
            statement = statement.offset((page - 1) * limit).limit(limit)
        statement = statement.order_by(MessageSession.update_time.desc())
        with session_getter() as session:
            print("filter_session Compiled SQL:",statement.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True}))
            return session.exec(statement).all()

    @classmethod
    def filter_session_count(cls, chat_ids: List[str] = None, review_status: List[ReviewStatus] = None,
                             flow_ids: List[str] = None, user_ids: List[int] = None, feedback: str = None,
                             start_date: datetime = None, end_date: datetime = None, include_delete: bool = True,
                             exclude_chats: List[str] = None) -> int:
        statement = select(func.count(MessageSession.chat_id))
        statement = cls.generate_filter_session_statement(statement, chat_ids, review_status, flow_ids, user_ids,
                                                          feedback, start_date, end_date, include_delete, exclude_chats)
        with session_getter() as session:
            return session.scalar(statement)

    @classmethod
    def add_like_count(cls, chat_id: str, like_count: int):
        if like_count == 0:
            return
        statement = update(MessageSession).where(MessageSession.chat_id == chat_id).values(
            like=MessageSession.like + like_count)
        with session_getter() as session:
            session.exec(statement)
            session.commit()

    @classmethod
    def add_dislike_count(cls, chat_id: str, dislike_count: int):
        if dislike_count == 0:
            return
        statement = update(MessageSession).where(MessageSession.chat_id == chat_id).values(
            dislike=MessageSession.dislike + dislike_count)
        with session_getter() as session:
            session.exec(statement)
            session.commit()

    @classmethod
    def add_copied_count(cls, chat_id: str, copied_count: int):
        if copied_count == 0:
            return
        statement = update(MessageSession).where(MessageSession.chat_id == chat_id).values(
            copied=MessageSession.copied + copied_count)
        with session_getter() as session:
            session.exec(statement)
            session.commit()