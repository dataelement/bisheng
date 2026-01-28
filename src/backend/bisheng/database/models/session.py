from datetime import datetime
from enum import Enum
from typing import Optional, List

from sqlmodel import Field, Column, DateTime, text, select, func, update

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_sync_db_session, get_async_db_session


class SensitiveStatus(Enum):
    PASS = 1  # Setuju
    VIOLATIONS = 2  # violates regulation


class MessageSessionBase(SQLModelSerializable):
    """ Conversation table """
    chat_id: str = Field(default=None, primary_key=True, description='Session UniqueID')
    flow_id: str = Field(index=True, description='Apply UniqueID')
    flow_type: int = Field(description='App type. Skills, assistants, workflows')
    flow_name: str = Field(index=True, description='Application name')
    flow_description: Optional[str] = Field(default=None, description='App Description')
    flow_logo: Optional[str] = Field(default=None, description='Applicationslogo')
    user_id: int = Field(index=True, description='User who created the sessionID')
    is_delete: Optional[bool] = Field(default=False, description='Whether the corresponding skill or the session itself was deleted')
    like: Optional[int] = Field(default=0, description='Number of liked messages')
    dislike: Optional[int] = Field(default=0, description='Number of messages clicked')
    copied: Optional[int] = Field(default=0, description='Number of messages copied')
    sensitive_status: int = Field(default=SensitiveStatus.PASS.value, description='Review Status')
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))


class MessageSession(MessageSessionBase, table=True):
    __tablename__ = 'message_session'


class MessageSessionDao(MessageSessionBase):

    @classmethod
    def insert_one(cls, data: MessageSession) -> MessageSession:
        with get_sync_db_session() as session:
            session.add(data)
            session.commit()
            session.refresh(data)
            return data

    @classmethod
    async def async_insert_one(cls, data: MessageSession) -> MessageSession:
        async with get_async_db_session() as session:
            session.add(data)
            await session.commit()
            await session.refresh(data)
            return data

    @classmethod
    def delete_session(cls, chat_id: str):
        statement = update(MessageSession).where(MessageSession.chat_id == chat_id).values(is_delete=True)
        with get_sync_db_session() as session:
            session.exec(statement)
            session.commit()

    @classmethod
    def get_one(cls, chat_id: str) -> MessageSession | None:
        statement = select(MessageSession).where(MessageSession.chat_id == chat_id)
        with get_sync_db_session() as session:
            return session.exec(statement).first()

    @classmethod
    async def async_get_one(cls, chat_id: str) -> MessageSession | None:
        statement = select(MessageSession).where(MessageSession.chat_id == chat_id)
        async with get_async_db_session() as session:
            return (await session.exec(statement)).first()

    @classmethod
    def generate_filter_session_statement(cls,
                                          statement,
                                          chat_ids: List[str] = None,
                                          sensitive_status: List[SensitiveStatus] = None,
                                          flow_ids: List[str] = None,
                                          user_ids: List[int] = None,
                                          feedback: str = None,
                                          start_date: datetime = None,
                                          end_date: datetime = None,
                                          include_delete: bool = True,
                                          exclude_chats: List[str] = None,
                                          flow_type: int = None):
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
            statement = statement.where(MessageSession.is_delete == False)  # noqa
        if exclude_chats:
            statement = statement.where(MessageSession.chat_id.not_in(exclude_chats))
        if start_date:
            statement = statement.where(MessageSession.create_time >= start_date)
        if end_date:
            statement = statement.where(MessageSession.create_time <= end_date)
        if sensitive_status:
            statement = statement.where(
                MessageSession.sensitive_status.in_([one.value for one in sensitive_status]))
        if flow_type:
            statement = statement.where(MessageSession.flow_type.in_(flow_type))
        return statement

    @classmethod
    def filter_session(cls,
                       chat_ids: List[str] = None,
                       sensitive_status: List[SensitiveStatus] = None,
                       flow_ids: List[str] = None,
                       user_ids: List[int] = None,
                       feedback: str = None,
                       start_date: datetime = None,
                       end_date: datetime = None,
                       include_delete: bool = True,
                       exclude_chats: List[str] = None,
                       page: int = 0,
                       limit: int = 0,
                       flow_type: List[int] = None) -> List[MessageSession]:
        statement = select(MessageSession)
        statement = cls.generate_filter_session_statement(statement,
                                                          chat_ids,
                                                          sensitive_status,
                                                          flow_ids,
                                                          user_ids,
                                                          feedback,
                                                          start_date,
                                                          end_date,
                                                          include_delete,
                                                          exclude_chats,
                                                          flow_type=flow_type)
        if page and limit:
            statement = statement.offset((page - 1) * limit).limit(limit)
        statement = statement.order_by(MessageSession.create_time.desc())
        with get_sync_db_session() as session:
            return session.exec(statement).all()

    @classmethod
    def filter_session_count(cls,
                             chat_ids: List[str] = None,
                             sensitive_status: List[SensitiveStatus] = None,
                             flow_ids: List[str] = None,
                             user_ids: List[int] = None,
                             feedback: str = None,
                             start_date: datetime = None,
                             end_date: datetime = None,
                             include_delete: bool = True,
                             exclude_chats: List[str] = None,
                             flow_type: List[int] = None) -> int:
        statement = select(func.count(MessageSession.chat_id))
        statement = cls.generate_filter_session_statement(statement, chat_ids, sensitive_status,
                                                          flow_ids, user_ids, feedback, start_date,
                                                          end_date, include_delete, exclude_chats, flow_type=flow_type)
        with get_sync_db_session() as session:
            return session.scalar(statement)

    @classmethod
    def update_sensitive_status(cls, chat_id: str, sensitive_status: SensitiveStatus):
        statement = update(MessageSession).where(MessageSession.chat_id == chat_id).values(
            sensitive_status=sensitive_status.value)
        with get_sync_db_session() as session:
            session.exec(statement)
            session.commit()

    @classmethod
    def add_like_count(cls, chat_id: str, like_count: int):
        if like_count == 0:
            return
        statement = update(MessageSession).where(MessageSession.chat_id == chat_id).values(
            like=MessageSession.like + like_count)
        with get_sync_db_session() as session:
            session.exec(statement)
            session.commit()

    @classmethod
    def add_dislike_count(cls, chat_id: str, dislike_count: int):
        if dislike_count == 0:
            return
        statement = update(MessageSession).where(MessageSession.chat_id == chat_id).values(
            dislike=MessageSession.dislike + dislike_count)
        with get_sync_db_session() as session:
            session.exec(statement)
            session.commit()

    @classmethod
    def add_copied_count(cls, chat_id: str, copied_count: int):
        if copied_count == 0:
            return
        statement = update(MessageSession).where(MessageSession.chat_id == chat_id).values(
            copied=MessageSession.copied + copied_count)
        with get_sync_db_session() as session:
            session.exec(statement)
            session.commit()

    @classmethod
    def update_session_info_by_flow(cls, name: str, description: str, logo: str, flow_id: str, flow_type: int):
        statement = update(MessageSession).where(
            MessageSession.flow_id == flow_id,
            MessageSession.flow_type == flow_type
        ).values(
            flow_name=name,
            flow_description=description,
            flow_logo=logo
        )
        with get_sync_db_session() as session:
            session.exec(statement)
            session.commit()
