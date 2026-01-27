from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Tuple

from loguru import logger
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlmodel import (JSON, Column, DateTime, Field, String, Text, case, delete, func, not_, or_,
                      select, text, update, col)

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_sync_db_session, get_async_db_session


class LikedType(Enum):
    UNRATED = 0  # Not assessed
    LIKED = 1  # Love
    DISLIKED = 2  # don't like}


class MessageBase(SQLModelSerializable):
    is_bot: bool = Field(index=False, description='Chat Role')
    source: Optional[int] = Field(default=None, index=False, description='Whether traceability is supported')
    mark_status: Optional[int] = Field(index=False, default=1, description='Tag status')
    mark_user: Optional[int] = Field(default=None, index=False, description='Flagging User')
    mark_user_name: Optional[str] = Field(default=None, index=False, description='Flagging User')
    message: Optional[str] = Field(default=None, sa_column=Column(LONGTEXT), description='Chat Message')
    extra: Optional[str] = Field(default=None, sa_column=Column(Text), description='Connection information, etc.')
    type: str = Field(index=False, description='Type of Message')
    category: str = Field(index=False, max_length=32, description='Message category, questionetc.')
    flow_id: str = Field(index=True, description='Corresponding Skillsid')
    chat_id: Optional[str] = Field(default=None, index=True, description='chat_id, Frontend Generation')
    user_id: Optional[int] = Field(default=None, index=True, description='Usersid')
    liked: Optional[int] = Field(index=False, default=0, description="Whether the user likes it or 0Not assessed/1 Love/2 don't like}")
    solved: Optional[int] = Field(index=False, default=0, description='Whether the user likes it or 0Not assessed/1 Solution/2 Unresolve')
    copied: Optional[int] = Field(index=False, default=0, description='Is the user copying 0: Not copied 1Copied: ')
    sensitive_status: Optional[int] = Field(index=False, default=1, description='Sensitive Word Status 1Pass 2violates regulation')
    sender: Optional[str] = Field(index=False, default='', description='autogen Sender')
    receiver: Optional[Dict] = Field(index=False, default=None, description='autogen Sender')
    intermediate_steps: Optional[str] = Field(default=None, sa_column=Column(Text), description='Process Log')
    files: Optional[str] = Field(default=None, sa_column=Column(String(length=4096)), description='Uploaded documents, etc.')
    remark: Optional[str] = Field(default=None, sa_column=Column(String(length=4096)),
                                  description='Note. break_answer: Interrupted response inactionhistoryPass to Model')
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))


class ChatMessage(MessageBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    receiver: Optional[Dict] = Field(default=None, sa_column=Column(JSON))

    # Key: Set table level character set to utf8mb4
    __table_args__ = {
        "mysql_charset": "utf8mb4",
        "mysql_collate": "utf8mb4_unicode_ci"
    }


class ChatMessageRead(MessageBase):
    id: Optional[int] = None


class ChatMessageQuery(MessageBase):
    id: Optional[int] = None
    receiver: Optional[Dict] = None


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

        with get_sync_db_session() as session:
            return session.scalar(base_condition)

    @classmethod
    def app_list_group_by_chat_id(
            cls,
            page_size: int,
            page_num: int,
            flow_ids: Optional[list[str]],
            user_ids: Optional[list[int]],
    ) -> Tuple[List[Dict], int]:
        with get_sync_db_session() as session:
            count_stat = select(func.count(func.distinct(ChatMessage.chat_id)))
            sql = select(
                ChatMessage.chat_id,
                ChatMessage.user_id,
                ChatMessage.flow_id,
                func.max(ChatMessage.create_time).label('create_time'),
                func.sum(case((ChatMessage.liked == 1, 1), else_=0)),
                func.sum(case((ChatMessage.liked == 2, 1), else_=0)),
                func.sum(case((ChatMessage.copied == 1, 1), else_=0)),
            )

            if flow_ids:
                count_stat = count_stat.where(ChatMessage.flow_id.in_(flow_ids))
                sql = sql.where(ChatMessage.flow_id.in_(flow_ids))
            if user_ids:
                count_stat = count_stat.where(
                    or_(
                        ChatMessage.mark_user.in_(user_ids),
                        ChatMessage.mark_status == 1,
                    ))
                sql = sql.where(
                    or_(ChatMessage.mark_user.in_(user_ids), ChatMessage.mark_status == 1))
            sql = sql.group_by(ChatMessage.chat_id, ChatMessage.user_id,
                               ChatMessage.flow_id).order_by(
                func.max(ChatMessage.create_time).desc()).offset(
                page_size * (page_num - 1)).limit(page_size)

            res_list = session.exec(sql).all()
            total_count = session.scalar(count_stat)

            dict_res = [{
                'chat_id': chat_id,
                'user_id': user_id,
                'flow_id': flow_id,
                'like_count': like_num,
                'dislike_count': dislike_num,
                'copied_count': copied_num,
                'create_time': create_time
            } for chat_id, user_id, flow_id, create_time, like_num, dislike_num, copied_num in
                res_list]
            logger.info(res_list)
            return dict_res, total_count


class ChatMessageDao(MessageBase):

    @classmethod
    def get_latest_message_by_chatid(cls, chat_id: str):
        statement = select(ChatMessage).where(ChatMessage.chat_id == chat_id).order_by(
            ChatMessage.id.desc()).limit(1)
        with get_sync_db_session() as session:
            res = session.exec(statement).all()
            if res:
                return res[0]
            else:
                return None

    @classmethod
    async def aget_latest_message_by_chatid(cls, chat_id: str):
        statement = select(ChatMessage).where(ChatMessage.chat_id == chat_id).order_by(
            ChatMessage.id.desc()).limit(1)
        async with get_async_db_session() as session:
            res = await session.exec(statement)
            res = res.all()
            if res:
                return res[0]
            else:
                return None

    @classmethod
    def get_latest_message_by_chat_ids(cls,
                                       chat_ids: list[str],
                                       category: str = None,
                                       exclude_category: str = None):
        """
        Get the most recent message content for each session
        """
        statement = select(ChatMessage.chat_id,
                           func.max(ChatMessage.id)).where(ChatMessage.chat_id.in_(chat_ids))
        if category:
            statement = statement.where(ChatMessage.category == category)
        if exclude_category:
            statement = statement.where(ChatMessage.category != exclude_category)
        statement = statement.group_by(ChatMessage.chat_id)
        with get_sync_db_session() as session:
            # Get the latestidVertical
            res = session.exec(statement).all()
            ids = [one[1] for one in res]
            # Get the details of your message
            statement = select(ChatMessage).where(ChatMessage.id.in_(ids))
            return session.exec(statement).all()

    @classmethod
    def get_messages_by_chat_id(cls,
                                chat_id: str,
                                category_list: list = None,
                                limit: int = 10) -> List[ChatMessage]:
        with get_sync_db_session() as session:
            statement = select(ChatMessage).where(ChatMessage.chat_id == chat_id)
            if category_list:
                statement = statement.where(ChatMessage.category.in_(category_list))
            statement = statement.limit(limit).order_by(ChatMessage.create_time.asc())
            return session.exec(statement).all()

    @classmethod
    async def aget_messages_by_chat_id(cls,
                                       chat_id: str,
                                       category_list: list = None,
                                       limit: int = 10) -> List[ChatMessage]:
        async with get_async_db_session() as session:
            statement = select(ChatMessage).where(ChatMessage.chat_id == chat_id)
            if category_list:
                statement = statement.where(ChatMessage.category.in_(category_list))
            statement = statement.limit(limit).order_by(ChatMessage.create_time.asc())
            result = await session.exec(statement)
            return result.all()

    @classmethod
    def get_last_msg_by_flow_id(cls, flow_id: List[str], chat_id: List[str]):
        with get_sync_db_session() as session:
            statement = select(ChatMessage.chat_id,
                               ChatMessage.flow_id).where(ChatMessage.flow_id.in_(flow_id)).where(
                not_(ChatMessage.chat_id.in_(chat_id))).group_by(
                ChatMessage.chat_id, ChatMessage.flow_id)
            return session.exec(statement).all()

    @classmethod
    def get_msg_by_chat_id(cls, chat_id: str):
        with get_sync_db_session() as session:
            statement = select(ChatMessage).where(ChatMessage.chat_id == chat_id)
            return session.exec(statement).all()

    @classmethod
    def get_msg_by_flow(cls, flow_id: str):
        with get_sync_db_session() as session:
            # sql = text("select chat_id,count(*) as chat_count from chatmessage where flow_id=:flow_id group by chat_id") # noqa
            st = select(ChatMessage.chat_id).where(ChatMessage.flow_id == flow_id).group_by(
                ChatMessage.chat_id)
            return session.exec(st).all()

    @classmethod
    def get_msg_by_flows(cls, flow_id: List[str]):
        with get_sync_db_session() as session:
            st = select(ChatMessage.chat_id).where(ChatMessage.flow_id.in_(flow_id)).group_by(
                ChatMessage.chat_id)
            return session.exec(st).all()

    @classmethod
    def delete_by_user_chat_id(cls, user_id: int, chat_id: str):
        if user_id is None or chat_id is None:
            logger.info('delete_param_error user_id={} chat_id={}', user_id, chat_id)
            return False

        statement = delete(ChatMessage).where(ChatMessage.chat_id == chat_id,
                                              ChatMessage.user_id == user_id)

        with get_sync_db_session() as session:
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

        with get_sync_db_session() as session:
            session.exec(statement)
            session.commit()
        return True

    @classmethod
    def insert_one(cls, message: ChatMessage) -> ChatMessage:
        with get_sync_db_session() as session:
            session.add(message)
            session.commit()
            session.refresh(message)
        return message

    @classmethod
    async def ainsert_one(cls, message: ChatMessage) -> ChatMessage:
        async with get_async_db_session() as session:
            session.add(message)
            await session.commit()
            await session.refresh(message)
        return message

    @classmethod
    def insert_batch(cls, messages: List[ChatMessage]):
        with get_sync_db_session() as session:
            session.add_all(messages)
            session.commit()
            ret = []
            for one in messages:
                session.refresh(one)
                ret.append(one)
            return ret

    @classmethod
    def get_message_by_id(cls, message_id: int) -> Optional[ChatMessage]:
        with get_sync_db_session() as session:
            return session.exec(select(ChatMessage).where(ChatMessage.id == message_id)).first()

    @classmethod
    async def aget_message_by_id(cls, message_id: int) -> Optional[ChatMessage]:
        async with get_async_db_session() as session:
            result = await session.exec(select(ChatMessage).where(ChatMessage.id == message_id))
            return result.first()

    @classmethod
    def update_message(cls, message_id: int, user_id: int, message: str):
        with get_sync_db_session() as session:
            statement = update(ChatMessage).where(ChatMessage.id == message_id).where(
                ChatMessage.user_id == user_id).values(message=message)
            session.exec(statement)
            session.commit()

    @classmethod
    def update_message_model(cls, message: ChatMessage):
        with get_sync_db_session() as session:
            session.add(message)
            session.commit()
            session.refresh(message)
        return message

    @classmethod
    async def aupdate_message_model(cls, message: ChatMessage):
        async with get_async_db_session() as session:
            session.add(message)
            await session.commit()
            await session.refresh(message)
        return message

    @classmethod
    def update_message_copied(cls, message_id: int, copied: int):
        with get_sync_db_session() as session:
            statement = update(ChatMessage).where(ChatMessage.id == message_id).values(
                copied=copied)
            session.exec(statement)
            session.commit()

    @classmethod
    def update_message_mark(cls, chat_id: str, status: int):
        with get_sync_db_session() as session:
            statement = update(ChatMessage).where(ChatMessage.chat_id == chat_id).values(
                mark_status=status)
            session.exec(statement)
            session.commit()

    @classmethod
    async def get_all_message_by_chat_ids(cls, chat_ids: List[str]) -> List[ChatMessage]:
        statement = select(ChatMessage).where(ChatMessage.chat_id.in_(chat_ids)).order_by(
            ChatMessage.create_time.asc())
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    async def afilter_message_by_chat_id(cls, chat_id: str, flow_id: str, message_id: int = None, page_size: int = 20) \
            -> List[ChatMessage]:
        statement = select(ChatMessage).where(ChatMessage.chat_id == chat_id).where(ChatMessage.flow_id == flow_id)
        if message_id:
            statement = statement.where(ChatMessage.id < message_id)
        statement = statement.order_by(col(ChatMessage.id).desc()).limit(page_size)
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()
