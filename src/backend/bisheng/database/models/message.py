from datetime import datetime
from typing import Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy.sql import not_

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import JSON, Column, DateTime, String, Text, case, func, or_, text, update
from sqlmodel import Field, delete, select


class MessageBase(SQLModelSerializable):
    is_bot: bool = Field(index=False, description='聊天角色')
    source: Optional[int] = Field(index=False, description='是否支持溯源')
    mark_status: Optional[int] = Field(index=False,default=1, description='标记状态')
    mark_user: Optional[int] = Field(index=False, description='标记用户')
    mark_user_name: Optional[str] = Field(index=False, description='标记用户')
    message: Optional[str] = Field(sa_column=Column(Text), description='聊天消息')
    extra: Optional[str] = Field(sa_column=Column(String(length=4096)), description='连接信息等')
    type: str = Field(index=False, description='消息类型')
    category: str = Field(index=False, description='消息类别， question等')
    flow_id: UUID = Field(index=True, description='对应的技能id')
    chat_id: Optional[str] = Field(index=True, description='chat_id, 前端生成')
    user_id: Optional[str] = Field(index=True, description='用户id')
    liked: Optional[int] = Field(index=False, default=0, description='用户是否喜欢 0未评价/1 喜欢/2 不喜欢')
    solved: Optional[int] = Field(index=False, default=0, description='用户是否喜欢 0未评价/1 解决/2 未解决')
    copied: Optional[int] = Field(index=False, default=0, description='用户是否复制 0：未复制 1：已复制')
    sender: Optional[str] = Field(index=False, default='', description='autogen 的发送方')
    receiver: Optional[Dict] = Field(index=False, default=None, description='autogen 的发送方')
    intermediate_steps: Optional[str] = Field(sa_column=Column(Text), description='过程日志')
    files: Optional[str] = Field(sa_column=Column(String(length=4096)), description='上传的文件等')
    remark: Optional[str] = Field(sa_column=Column(String(length=4096)),
                                  description='备注。break_answer: 中断的回复不作为history传给模型')
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

    @classmethod
    def app_list_group_by_chat_id(
            cls,
            page_size: int,
            page_num: int,
            flow_ids: Optional[list[str]],
            user_ids: Optional[list[int]],
    ) -> Tuple[List[Dict], int]:
        with session_getter() as session:
            count_stat = select(func.count(func.distinct(ChatMessage.chat_id)))
            sql = select(ChatMessage.chat_id, ChatMessage.user_id, ChatMessage.flow_id,
                         func.max(ChatMessage.create_time).label('create_time'),
                         func.sum(case((ChatMessage.liked == 1, 1), else_=0)),
                         func.sum(case((ChatMessage.liked == 2, 1), else_=0)),
                         func.sum(case((ChatMessage.copied == 1, 1), else_=0)), )

            if flow_ids:
                count_stat = count_stat.where(ChatMessage.flow_id.in_(flow_ids))
                sql = sql.where(ChatMessage.flow_id.in_(flow_ids))
            if user_ids:
                count_stat = count_stat.where(or_(
                    ChatMessage.mark_user.in_(user_ids),
                    ChatMessage.mark_status==1,
                                                 ))
                sql = sql.where(or_(ChatMessage.mark_user.in_(user_ids),
                                    ChatMessage.mark_status==1))
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
            } for chat_id, user_id, flow_id, create_time, like_num, dislike_num, copied_num in res_list]
            logger.info(res_list)
            return dict_res, total_count


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
    def get_latest_message_by_chat_ids(cls, chat_ids: list[str], category: str = None):
        """
        获取每个会话最近的一次消息内容
        """
        statement = select(ChatMessage.chat_id,
                           func.max(ChatMessage.id)).where(ChatMessage.chat_id.in_(chat_ids))
        if category:
            statement = statement.where(ChatMessage.category == category)
        statement = statement.group_by(ChatMessage.chat_id)
        with session_getter() as session:
            # 获取最新的id列表
            res = session.exec(statement).all()
            ids = [one[1] for one in res]
            # 获取消息的具体内容
            statement = select(ChatMessage).where(ChatMessage.id.in_(ids))
            return session.exec(statement).all()

    @classmethod
    def get_messages_by_chat_id(cls, chat_id: str, category_list: list = None, limit: int = 10):
        with session_getter() as session:
            statement = select(ChatMessage).where(ChatMessage.chat_id == chat_id)
            if category_list:
                statement = statement.where(ChatMessage.category.in_(category_list))
            statement = statement.limit(limit).order_by(ChatMessage.create_time.asc())
            return session.exec(statement).all()

    @classmethod
    def get_last_msg_by_flow_id(cls, flow_id: List[str],chat_id:List[str]):
        with session_getter() as session:
            statement = select(ChatMessage).where(ChatMessage.flow_id.in_(flow_id)).where(not_(ChatMessage.chat_id.in_(chat_id))).group_by(ChatMessage.chat_id).order_by(
                ChatMessage.create_time)
            return session.exec(statement).all()

    @classmethod
    def get_msg_by_chat_id(cls, chat_id: str):
        with session_getter() as session:
            statement = select(ChatMessage).where(ChatMessage.chat_id == chat_id)
            return session.exec(statement).all()

    @classmethod
    def get_msg_by_flow(cls, flow_id: str):
        with session_getter() as session:
            # sql = text("select chat_id,count(*) as chat_count from chatmessage where flow_id=:flow_id group by chat_id")
            st = select(ChatMessage).where(ChatMessage.flow_id == flow_id).group_by(ChatMessage.chat_id)
            return session.exec(st).all()

    @classmethod
    def get_msg_by_flows(cls, flow_id: List[str]):
        ids = [UUID(i) for i in flow_id]
        with session_getter() as session:
            # sql = text("select chat_id,count(*) as chat_count from chatmessage where flow_id=:flow_id group by chat_id")
            st = select(ChatMessage).where(ChatMessage.flow_id.in_(ids)).group_by(ChatMessage.chat_id)
            return session.exec(st).all()

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

    @classmethod
    def insert_batch(cls, messages: List[ChatMessage]):
        with session_getter() as session:
            session.add_all(messages)
            session.commit()

    @classmethod
    def get_message_by_id(cls, message_id: int) -> Optional[ChatMessage]:
        with session_getter() as session:
            return session.exec(select(ChatMessage).where(ChatMessage.id == message_id)).first()

    @classmethod
    def update_message(cls, message_id: int, user_id: int, message: str):
        with session_getter() as session:
            statement = update(ChatMessage).where(ChatMessage.id == message_id).where(
                ChatMessage.user_id == user_id).values(message=message)
            session.exec(statement)
            session.commit()

    @classmethod
    def update_message_model(cls, message: ChatMessage):
        with session_getter() as session:
            session.add(message)
            session.commit()
            session.refresh(message)
        return message

    @classmethod
    def update_message_copied(cls, message_id: int, copied: int):
        with session_getter() as session:
            statement = update(ChatMessage).where(ChatMessage.id == message_id).values(copied=copied)
            session.exec(statement)
            session.commit()

    @classmethod
    def update_message_mark(cls, chat_id: str, status: int):
        with session_getter() as session:
            statement = update(ChatMessage).where(ChatMessage.chat_id == chat_id).values(mark_status=status)
            session.exec(statement)
            session.commit()
