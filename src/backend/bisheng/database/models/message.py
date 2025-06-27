from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Tuple

from loguru import logger
from pydantic import BaseModel
from sqlalchemy import and_, tuple_
from sqlmodel import Field, delete, select, JSON, Column, DateTime, String, Text, case, func, or_, text, update, not_

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable
from bisheng.database.models.session import ReviewStatus
from bisheng.database.models.user_group import UserGroup
from bisheng.database.models.session import MessageSession
from bisheng.utils.sysloger import syslog_client


class ChatMessageType(Enum):
    # 已废弃
    FLOW = 'flow'  # 表示技能会话消息
    ASSISTANT = 'assistant'  # 表示助手会话消息
    WORKFLOW = 'workflow'  # 表示工作流会话消息

class LikedType(Enum):
    UNRATED = 0  # 未评价
    LIKED = 1  # 喜欢
    DISLIKED = 2  # 不喜欢

class MessageBase(SQLModelSerializable):
    is_bot: bool = Field(index=False, description='聊天角色')
    source: Optional[int] = Field(default=None, index=False, description='是否支持溯源')
    mark_status: Optional[int] = Field(index=False, default=1, description='标记状态')
    mark_user: Optional[int] = Field(default=None, index=False, description='标记用户')
    mark_user_name: Optional[str] = Field(default=None, index=False, description='标记用户')
    message: Optional[str] = Field(default=None, sa_column=Column(Text), description='聊天消息')
    extra: Optional[str] = Field(default=None, sa_column=Column(Text), description='连接信息等')
    type: str = Field(index=False, description='消息类型')
    category: str = Field(index=False, max_length=32, description='消息类别， question等')
    flow_id: str = Field(index=True, description='对应的技能id')
    chat_id: Optional[str] = Field(default=None, index=True, description='chat_id, 前端生成')
    user_id: Optional[int] = Field(default=None, index=True, description='用户id')
    liked: Optional[int] = Field(index=False, default=0, description='用户是否喜欢 0未评价/1 喜欢/2 不喜欢')
    solved: Optional[int] = Field(index=False, default=0, description='用户是否喜欢 0未评价/1 解决/2 未解决')
    copied: Optional[int] = Field(index=False, default=0, description='用户是否复制 0：未复制 1：已复制')
    sensitive_status: Optional[int] = Field(index=False, default=1, description='敏感词状态 1：通过 2：违规')
    sender: Optional[str] = Field(index=False, default='', description='autogen 的发送方')
    receiver: Optional[Dict] = Field(index=False, default=None, description='autogen 的发送方')
    intermediate_steps: Optional[str] = Field(default=None, sa_column=Column(Text), description='过程日志')
    files: Optional[str] = Field(default=None, sa_column=Column(String(length=4096)), description='上传的文件等')
    remark: Optional[str] = Field(default=None, sa_column=Column(String(length=4096)),
                                  description='备注。break_answer: 中断的回复不作为history传给模型')
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP'),
        onupdate=text('CURRENT_TIMESTAMP')))
    review_status: Optional[int] = Field(index=True, default=ReviewStatus.DEFAULT.value, description='会话审查状态')
    review_reason: Optional[str] = Field(sa_column=Column(String(length=4096)), default='', description='会话审查原因')


class ChatMessage(MessageBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    receiver: Optional[Dict] = Field(default=None, sa_column=Column(JSON))


class ChatMessageRead(MessageBase):
    id: Optional[int] = None


class ChatMessageQuery(BaseModel):
    id: Optional[int] = None
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
            flow_ids: Optional[list[str]] = None,
            user_ids: Optional[list[int]] = None,
            mark_user_ids: Optional[list[int]] = None,
            start_date: datetime = None,
            end_date: datetime = None,
            feedback: str = None,
            exclude_flow_ids: List[str] = None,
            chat_ids: List[str] = None,
            exclude_chat_ids: List[str] = None,
    ) -> Tuple[List[Dict], int]:
        with session_getter() as session:
            count_stat = select(func.count(func.distinct(ChatMessage.chat_id)))
            sql = select(ChatMessage.chat_id, ChatMessage.user_id, ChatMessage.flow_id,
                         func.min(ChatMessage.create_time).label('create_time'),
                         func.sum(case((ChatMessage.liked == 1, 1), else_=0)),
                         func.sum(case((ChatMessage.liked == 2, 1), else_=0)),
                         func.sum(case((ChatMessage.copied == 1, 1), else_=0)))

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


            if mark_user_ids:
                count_stat = count_stat.where(or_(
                    ChatMessage.mark_user.in_(mark_user_ids),
                    ChatMessage.mark_status == 1,
                ))
                sql = sql.where(or_(ChatMessage.mark_user.in_(mark_user_ids),
                                    ChatMessage.mark_status == 1))
            # if user_ids:
            #     count_stat = count_stat.where(ChatMessage.user_id.in_(user_ids))
            #     sql = sql.where(ChatMessage.user_id.in_(user_ids))

            if start_date:
                count_stat = count_stat.where(ChatMessage.create_time >= start_date)
                sql = sql.where(ChatMessage.create_time >= start_date)
            if end_date:
                count_stat = count_stat.where(ChatMessage.create_time <= end_date)
                sql = sql.where(ChatMessage.create_time <= end_date)
            if chat_ids:
                count_stat = count_stat.where(ChatMessage.chat_id.in_(chat_ids))
                sql = sql.where(ChatMessage.chat_id.in_(chat_ids))
            if exclude_chat_ids:
                count_stat = count_stat.where(ChatMessage.chat_id.not_in(exclude_chat_ids))
                sql = sql.where(ChatMessage.chat_id.not_in(exclude_chat_ids))
            if feedback == 'like':
                count_stat = count_stat.where(ChatMessage.liked == 1)
                sql = sql.where(ChatMessage.liked == 1)
            elif feedback == 'dislike':
                count_stat = count_stat.where(ChatMessage.liked == 2)
                sql = sql.where(ChatMessage.liked == 2)
            elif feedback == 'copied':
                count_stat = count_stat.where(ChatMessage.copied == 1)
                sql = sql.where(ChatMessage.copied == 1)

            if exclude_flow_ids:
                count_stat = count_stat.where(ChatMessage.flow_id.not_in(exclude_flow_ids))
                sql = sql.where(ChatMessage.flow_id.not_in(exclude_flow_ids))

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
        with session_getter() as session:
            res = session.exec(statement).all()
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
        获取每个会话最近的一次消息内容
        """
        statement = select(ChatMessage.chat_id,
                           func.max(ChatMessage.id)).where(ChatMessage.chat_id.in_(chat_ids))
        if category:
            statement = statement.where(ChatMessage.category == category)
        if exclude_category:
            statement = statement.where(ChatMessage.category != exclude_category)
        statement = statement.group_by(ChatMessage.chat_id)
        with session_getter() as session:
            # 获取最新的id列表
            res = session.exec(statement).all()
            ids = [one[1] for one in res]
            # 获取消息的具体内容
            statement = select(ChatMessage).where(ChatMessage.id.in_(ids))
            return session.exec(statement).all()

    @classmethod
    def get_messages_by_chat_id(cls,
                                chat_id: str,
                                category_list: list = None,
                                limit: int = 10) -> List[ChatMessage]:
        with session_getter() as session:
            statement = select(ChatMessage).where(ChatMessage.chat_id == chat_id)
            if category_list:
                statement = statement.where(ChatMessage.category.in_(category_list))
            statement = statement.limit(limit).order_by(ChatMessage.create_time.asc())
            return session.exec(statement).all()

    @classmethod
    def get_last_msg_by_flow_id(cls, flow_id: List[str], chat_id: List[str]):
        with session_getter() as session:
            statement = select(ChatMessage.chat_id,
                               ChatMessage.flow_id).where(ChatMessage.flow_id.in_(flow_id)).where(
                                   not_(ChatMessage.chat_id.in_(chat_id))).group_by(
                                       ChatMessage.chat_id, ChatMessage.flow_id)
            return session.exec(statement).all()

    @classmethod
    def get_msg_by_chat_id(cls, chat_id: str):
        with session_getter() as session:
            statement = select(ChatMessage).where(ChatMessage.chat_id == chat_id).order_by(ChatMessage.id.asc())
            return session.exec(statement).all()

    @classmethod
    def get_msg_by_flow(cls, flow_id: str):
        with session_getter() as session:
            # sql = text("select chat_id,count(*) as chat_count from chatmessage where flow_id=:flow_id group by chat_id") # noqa
            st = select(ChatMessage.chat_id).where(ChatMessage.flow_id == flow_id).group_by(
                ChatMessage.chat_id)
            return session.exec(st).all()

    @classmethod
    def get_msg_by_flows(cls, flow_id: List[str]):
        with session_getter() as session:
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
        statement = update(MessageSession).where(MessageSession.chat_id == message.chat_id).values(
            update_time = datetime.now(),
        )
        with session_getter() as session:
            session.exec(statement)
            session.add(message)
            session.commit()
            session.refresh(message)
            syslog_client.log_chat_message(message.to_dict())
        return message

    @classmethod
    def insert_batch(cls, messages: List[ChatMessage]):
        chat_ids = [message.chat_id for message in messages]
        statement = update(MessageSession).where(MessageSession.chat_id.in_(chat_ids)).values(
            update_time=datetime.now(),
        )
        with session_getter() as session:
            session.execute(statement)
            session.add_all(messages)
            syslog_data = [one.to_dict() for one in messages]
            session.commit()

            for message in syslog_data:
                syslog_client.log_chat_message(message)

            ret = []
            for one in messages:
                session.refresh(one)
                ret.append(one)
            return ret


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
            statement = update(ChatMessage).where(ChatMessage.id == message_id).values(
                copied=copied)
            session.exec(statement)
            session.commit()

    @classmethod
    def update_message_mark(cls, chat_id: str, status: int):
        with session_getter() as session:
            statement = update(ChatMessage).where(ChatMessage.chat_id == chat_id).values(
                mark_status=status)
            session.exec(statement)
            session.commit()

    @classmethod
    def get_all_message_by_chat_ids(cls, chat_ids: List[str]) -> List[ChatMessage]:
        statement = select(ChatMessage).where(ChatMessage.chat_id.in_(chat_ids)).order_by(
            ChatMessage.create_time.asc())
        with session_getter() as session:
            return session.exec(statement).all()

    @classmethod
    def update_review_status(cls, message_ids: List[int], review_status: int, review_reason: str = ''):
        """ 更新消息的审核状态 """
        statement = update(ChatMessage).where(ChatMessage.id.in_(message_ids)).values(review_status=review_status,
                                                                                      review_reason=review_reason)
        with session_getter() as session:
            session.exec(statement)
            session.commit()

    @classmethod
    def get_chat_info_group_by_app(cls, flow_ids: List[str], start_date: datetime, end_date: datetime, order_field: str,
                                   order_type: str, page: int, page_size: int,user_ids: List[str]=None):
        """ 获取会话的一些信息，根据技能来聚合 """
        count_stat = select(func.count(func.distinct(ChatMessage.flow_id)))
        sql = select(
            ChatMessage.flow_id,
            func.min(ChatMessage.user_id),
            func.count(func.distinct(ChatMessage.chat_id)).label('session_num'),
            func.sum(case((ChatMessage.category == 'question', 1), else_=0)).label('input_num'),
            func.sum(case((ChatMessage.category != 'question', 1), else_=0)).label('output_num'),
            func.sum(case((ChatMessage.review_status == ReviewStatus.VIOLATIONS.value, 1), else_=0)).label(
                'violations_num')
        )
        if flow_ids:
            sql = sql.where(ChatMessage.flow_id.in_(flow_ids))
            count_stat = count_stat.where(ChatMessage.flow_id.in_(flow_ids))
        if start_date:
            sql = sql.where(ChatMessage.create_time >= start_date)
            count_stat = count_stat.where(ChatMessage.create_time >= start_date)
        if end_date:
            sql = sql.where(ChatMessage.create_time <= end_date)
            count_stat = count_stat.where(ChatMessage.create_time <= end_date)
        if user_ids:
            sql = sql.where(ChatMessage.user_id.in_(user_ids))
            count_stat = count_stat.where(ChatMessage.user_id.in_(user_ids))

        sql = sql.group_by(ChatMessage.flow_id)
        if order_field and order_type:
            sql = sql.order_by(text(f'{order_field} {order_type}'))
            pass
        else:
            sql = sql.order_by(func.min(ChatMessage.create_time).desc())
        if page and page_size:
            sql = sql.offset((page - 1) * page_size).limit(page_size)

        with session_getter() as session:
            res_list = session.exec(sql).all()
            total = session.scalar(count_stat)
        res = [
            {
                'flow_id': one[0],
                'user_id': one[1],
                'session_num': one[2],
                'input_num': one[3],
                'output_num': one[4],
                'violations_num': one[5]
            } for one in res_list
        ]
        return res, total

    @classmethod
    def get_chat_id_by_time(cls, flow_ids: List[str]=None, start_time: datetime=None, end_time: datetime=None,
                            category: List[str] = None):
        statement = select(func.distinct(ChatMessage.chat_id))
        if flow_ids:
            statement = statement.where(ChatMessage.flow_id.in_(flow_ids))
        if start_time:
            statement = statement.where(ChatMessage.create_time >= start_time)
        if end_time:
            statement = statement.where(ChatMessage.create_time <= end_time)
        if category:
            statement = statement.where(ChatMessage.category.in_(category))
        from sqlalchemy.dialects import mysql
        print("get_chat_id_by_time Compiled SQL:",
              statement.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True}))
        with session_getter() as session:
            res = session.exec(statement).all()
            return res

    @classmethod
    def get_chat_like_num(self, flow_id: str, chat_id: str, start_time: datetime = None, end_time: datetime = None):
        # 构建统计查询，使用 count 函数统计 liked=1 的记录数
        statement = select(func.count()).where(
            ChatMessage.flow_id == flow_id,
            ChatMessage.chat_id == chat_id,
            ChatMessage.liked == 1  # 筛选 liked 为 1 的记录
        )

        # 添加时间范围筛选条件
        if start_time:
            statement = statement.where(ChatMessage.create_time >= start_time)
        if end_time:
            statement = statement.where(ChatMessage.create_time <= end_time)

        # 执行查询并返回统计结果
        with session_getter() as session:
            count = session.exec(statement).one()
            return count

    @classmethod
    def get_chat_dislike_num(self, flow_id: str, chat_id: str, start_time: datetime = None, end_time: datetime = None):
        # 构建统计查询，使用 count 函数统计 liked=1 的记录数
        statement = select(func.count()).where(
            ChatMessage.flow_id == flow_id,
            ChatMessage.chat_id == chat_id,
            ChatMessage.liked == 2
        )

        # 添加时间范围筛选条件
        if start_time:
            statement = statement.where(ChatMessage.create_time >= start_time)
        if end_time:
            statement = statement.where(ChatMessage.create_time <= end_time)

        # 执行查询并返回统计结果
        with session_getter() as session:
            count = session.exec(statement).one()
            return count

    @classmethod
    def get_chat_not_dislike_num(self, flow_id: str, chat_id: str, start_time: datetime = None, end_time: datetime = None):
        # 构建统计查询，使用 count 函数统计 liked=1 的记录数
        statement = select(func.count()).where(
            ChatMessage.flow_id == flow_id,
            ChatMessage.chat_id == chat_id,
            ChatMessage.liked != 2
        )

        # 添加时间范围筛选条件
        if start_time:
            statement = statement.where(ChatMessage.create_time >= start_time)
        if end_time:
            statement = statement.where(ChatMessage.create_time <= end_time)

        # 执行查询并返回统计结果
        with session_getter() as session:
            count = session.exec(statement).one()
            return count

    @classmethod
    def get_chat_copied_num(self, flow_id: str, chat_id: str, start_time: datetime = None, end_time: datetime = None):
        # 构建统计查询，使用 count 函数统计 liked=1 的记录数
        statement = select(func.count()).where(
            ChatMessage.flow_id == flow_id,
            ChatMessage.chat_id == chat_id,
            ChatMessage.copied == 1
        )

        # 添加时间范围筛选条件
        if start_time:
            statement = statement.where(ChatMessage.create_time >= start_time)
        if end_time:
            statement = statement.where(ChatMessage.create_time <= end_time)

        # 执行查询并返回统计结果
        with session_getter() as session:
            count = session.exec(statement).one()
            return count

    @classmethod
    def get_chat_info_group(cls, flow_ids: List[str], start_date: datetime, end_date: datetime, order_field: str,
                                   order_type: str, page: int, page_size: int,user_ids: List[str]=None):
        """ 获取会话的一些信息，根据技能来聚合 """
        count_stat = select(func.count(func.distinct(func.concat(ChatMessage.flow_id,UserGroup.group_id)))).select_from(ChatMessage
            ).join(UserGroup, ChatMessage.user_id == UserGroup.user_id)
        total_session_stat = select(
            func.count(func.distinct(func.concat(ChatMessage.chat_id, "-", ChatMessage.flow_id)))
        ).select_from(
            ChatMessage
        ).join(
            UserGroup, ChatMessage.user_id == UserGroup.user_id
        )
        # 构建主查询，明确指定连接的起始表和连接条件
        sql = select(
            ChatMessage.flow_id,
            UserGroup.group_id,
            func.count(func.distinct(ChatMessage.chat_id)).label('session_num'),
            func.sum(case(
                (ChatMessage.category == 'question', 1),
                else_=0
            )).label('input_num'),
            func.sum(case(
                (and_(ChatMessage.category != 'question', ChatMessage.category != 'user_input',ChatMessage.category != 'input'), 1),
                else_=0
            )).label('output_num'),
            func.sum(case(
                (ChatMessage.review_status == ReviewStatus.VIOLATIONS.value, 1),
                else_=0
            )).label('violations_num'),
            func.sum(case(
                (and_(ChatMessage.category != 'question', ChatMessage.liked == LikedType.UNRATED.value), 1),
                else_=0
            )).label('unrateds'),
            func.sum(case(
                (and_(ChatMessage.category != 'question', ChatMessage.liked == LikedType.LIKED.value), 1),
                else_=0
            )).label('likes'),
            func.sum(case(
                (and_(ChatMessage.category != 'question', ChatMessage.liked == LikedType.DISLIKED.value), 1),
                else_=0
            )).label('dislikes'),
            func.sum(case(
                (and_(
                    ChatMessage.category != 'question',
                    ChatMessage.category != 'user_input',
                    ChatMessage.category != 'input',
                    ChatMessage.liked != LikedType.DISLIKED.value
                ), 1),
                else_=0
            )).label('not_dislikes'),
            func.min(ChatMessage.user_id).label("user_id")
        ).select_from(ChatMessage).join(UserGroup, ChatMessage.user_id == UserGroup.user_id)

        if flow_ids:
            sql = sql.where(ChatMessage.flow_id.in_(flow_ids))
            count_stat = count_stat.where(ChatMessage.flow_id.in_(flow_ids))
            total_session_stat = total_session_stat.where(ChatMessage.flow_id.in_(flow_ids))
        if start_date:
            sql = sql.where(ChatMessage.create_time >= start_date)
            count_stat = count_stat.where(ChatMessage.create_time >= start_date)
            total_session_stat = total_session_stat.where(ChatMessage.create_time >= start_date)
        if end_date:
            sql = sql.where(ChatMessage.create_time <= end_date)
            count_stat = count_stat.where(ChatMessage.create_time <= end_date)
            total_session_stat = total_session_stat.where(ChatMessage.create_time <= end_date)
        if user_ids:
            sql = sql.where(ChatMessage.user_id.in_(user_ids))
            count_stat = count_stat.where(ChatMessage.user_id.in_(user_ids))
            total_session_stat = total_session_stat.where(ChatMessage.user_id.in_(user_ids))

        sql = sql.group_by(ChatMessage.flow_id,UserGroup.group_id)
        if order_field and order_type:
            sql = sql.order_by(text(f'{order_field} {order_type}'))
            pass
        else:
            sql = sql.order_by(func.min(ChatMessage.create_time).desc())
        if page and page_size:
            sql = sql.offset((page - 1) * page_size).limit(page_size)

        from sqlalchemy.dialects import mysql
        print("get_chat_info_group Compiled SQL:", sql.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True}))
        print("get_chat_info_group Compiled SQL Count:",
              count_stat.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True}))
        with session_getter() as session:
            res_list = session.exec(sql).all()
            total = session.scalar(count_stat)
            total_session_num = session.scalar(total_session_stat)
        res = [
            {
                'flow_id': one[0],
                'group_id': one[1],
                'session_num': one[2],
                'input_num': one[3],
                'output_num': one[4],
                'violations_num': one[5],
                'unrateds':one[6],
                'likes':one[7],
                'dislikes':one[8],
                'not_dislikes': one[9],
                'user_id': one[10],
                'satisfaction':one[7] / one[4] if one[4]!=0 and one[7] != 0 else 1,
                'not_nosatisfaction':one[9] / one[4] if one[4]!=0 and one[9] != 0 else 1,
            } for one in res_list
        ]
        
        # 返回结果，包含总session_num
        return {
            'data': res,
            'total': total or 0,
            'total_session_num': total_session_num or 0  # 处理可能的None值
        }
        