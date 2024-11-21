from datetime import datetime
from enum import Enum
from typing import List, Optional, Tuple
from uuid import UUID, uuid4

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable
from bisheng.database.models.role_access import AccessType, RoleAccess
from sqlalchemy import JSON, Column, DateTime, Text, and_, func, or_, text
from sqlmodel import Field, select


class AssistantStatus(Enum):
    OFFLINE = 0
    ONLINE = 1


class AssistantBase(SQLModelSerializable):
    id: Optional[UUID] = Field(nullable=False, primary_key=True, description='唯一ID')
    name: str = Field(default='', description='助手名称')
    logo: str = Field(default='', description='logo图片地址')
    desc: str = Field(default='', sa_column=Column(Text), description='助手描述')
    system_prompt: str = Field(default='', sa_column=Column(Text), description='系统提示词')
    prompt: str = Field(default='', sa_column=Column(Text), description='用户可见描述词')
    guide_word: Optional[str] = Field(default='', sa_column=Column(Text), description='开场白')
    guide_question: Optional[List] = Field(sa_column=Column(JSON), description='引导问题')
    model_name: str = Field(default='', description='对应模型管理里模型的唯一ID')
    temperature: float = Field(default=0.5, description='模型温度')
    status: int = Field(default=AssistantStatus.OFFLINE.value, description='助手是否上线')
    user_id: int = Field(default=0, description='创建用户ID')
    is_delete: int = Field(default=0, description='删除标志')
    create_time: Optional[datetime] = Field(sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=False,
                         server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))


class AssistantLinkBase(SQLModelSerializable):
    id: Optional[int] = Field(nullable=False, primary_key=True, description='唯一ID')
    assistant_id: Optional[UUID] = Field(index=True, description='助手ID')
    tool_id: Optional[int] = Field(default=0, index=True, description='工具ID')
    flow_id: Optional[str] = Field(default='', index=True, description='技能ID')
    knowledge_id: Optional[int] = Field(default=0, index=True, description='知识库ID')
    create_time: Optional[datetime] = Field(sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=False,
                         server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))


class Assistant(AssistantBase, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True, unique=True)


class AssistantLink(AssistantLinkBase, table=True):
    pass


class AssistantDao(AssistantBase):

    @classmethod
    def create_assistant(cls, data: Assistant) -> Assistant:
        with session_getter() as session:
            session.add(data)
            session.commit()
            session.refresh(data)
            return data

    @classmethod
    def update_assistant(cls, data: Assistant) -> Assistant:
        with session_getter() as session:
            session.add(data)
            session.commit()
            session.refresh(data)
            return data

    @classmethod
    def delete_assistant(cls, data: Assistant) -> Assistant:
        with session_getter() as session:
            data.is_delete = 1
            session.add(data)
            session.commit()
            session.refresh(data)
            return data

    @classmethod
    def get_one_assistant(cls, assistant_id: UUID) -> Assistant:
        with session_getter() as session:
            statement = select(Assistant).where(Assistant.id == assistant_id)
            return session.exec(statement).first()

    @classmethod
    def get_assistants_by_ids(cls, assistant_ids: List[UUID]) -> List[Assistant]:
        with session_getter() as session:
            statement = select(Assistant).where(Assistant.id.in_(assistant_ids))
            return session.exec(statement).all()

    @classmethod
    def get_assistant_by_name_user_id(cls, name: str, user_id: int) -> Assistant:
        with session_getter() as session:
            statement = select(Assistant).filter(Assistant.name == name,
                                                 Assistant.user_id == user_id,
                                                 Assistant.is_delete == 0)
            return session.exec(statement).first()

    @classmethod
    def get_assistants(cls, user_id: int, name: str, assistant_ids_extra: List[UUID],
                       status: Optional[int], page: int, limit: int, assistant_ids: List[UUID] = None) -> (
            List[Assistant], int):
        with session_getter() as session:
            count_statement = session.query(func.count(
                Assistant.id)).where(Assistant.is_delete == 0)
            statement = select(Assistant).where(Assistant.is_delete == 0)
            if assistant_ids_extra:
                # 需要or 加入的条件
                statement = statement.where(
                    or_(Assistant.id.in_(assistant_ids_extra), Assistant.user_id == user_id))
                count_statement = count_statement.where(
                    or_(Assistant.id.in_(assistant_ids_extra), Assistant.user_id == user_id))
            else:
                statement = statement.where(Assistant.user_id == user_id)
                count_statement = count_statement.where(Assistant.user_id == user_id)

            if assistant_ids:
                statement = statement.where(Assistant.id.in_(assistant_ids))
                count_statement = count_statement.where(Assistant.id.in_(assistant_ids))

            if name:
                statement = statement.where(or_(
                    Assistant.name.like(f'%{name}%'),
                    Assistant.desc.like(f'%{name}%')
                ))
                count_statement = count_statement.where(or_(
                    Assistant.name.like(f'%{name}%'),
                    Assistant.desc.like(f'%{name}%')
                ))
            if status is not None:
                statement = statement.where(Assistant.status == status)
                count_statement = count_statement.where(Assistant.status == status)
            if limit == 0 and page == 0:
                # 获取全部，不分页
                statement = statement.order_by(Assistant.update_time.desc())
            else:
                statement = statement.offset(
                    (page - 1) * limit).limit(limit).order_by(Assistant.update_time.desc())
            return session.exec(statement).all(), session.exec(count_statement).scalar()

    @classmethod
    def get_all_online_assistants(cls, flow_ids: List[UUID]) -> List[Assistant]:
        """ 获取所有已上线的助手 """
        statement = select(Assistant).filter(Assistant.status == AssistantStatus.ONLINE.value,
                                             Assistant.is_delete == 0)
        if flow_ids:
            statement = statement.where(Assistant.flow_id.in_(flow_ids))
        statement = statement.order_by(Assistant.update_time.desc())
        with session_getter() as session:
            return session.exec(statement).all()

    @classmethod
    def get_all_assistants(cls, name: str, page: int, limit: int, assistant_ids: List[UUID] = None,
                           status: int = None) -> (List[Assistant], int):
        with session_getter() as session:
            statement = select(Assistant).where(Assistant.is_delete == 0)
            count_statement = session.query(func.count(
                Assistant.id)).where(Assistant.is_delete == 0)
            if name:
                statement = statement.where(or_(
                    Assistant.name.like(f'%{name}%'),
                    Assistant.desc.like(f'%{name}%')
                ))
                count_statement = count_statement.where(or_(
                    Assistant.name.like(f'%{name}%'),
                    Assistant.desc.like(f'%{name}%')
                ))
            if assistant_ids:
                statement = statement.where(Assistant.id.in_(assistant_ids))
                count_statement = count_statement.where(Assistant.id.in_(assistant_ids))
            if status is not None:
                statement = statement.where(Assistant.status == status)
                count_statement = count_statement.where(Assistant.status == status)
            if page and limit:
                statement = statement.offset(
                    (page - 1) * limit
                ).limit(limit)
            statement = statement.order_by(Assistant.update_time.desc())
            return session.exec(statement).all(), session.exec(count_statement).scalar()

    @classmethod
    def get_assistants_by_access(cls, role_id: int, name: str, page_size: int,
                                 page_num: int) -> List[Tuple[Assistant, RoleAccess]]:
        statment = select(Assistant,
                          RoleAccess).join(RoleAccess,
                                           and_(RoleAccess.role_id == role_id,
                                                RoleAccess.type == AccessType.ASSISTANT_READ.value,
                                                RoleAccess.third_id == Assistant.id),
                                           isouter=True).where(Assistant.is_delete == 0)

        if name:
            statment = statment.where(Assistant.name.like('%' + name + '%'))
        if page_num and page_size and page_num != 'undefined':
            page_num = int(page_num)
            statment = statment.order_by(RoleAccess.type.desc()).order_by(
                Assistant.update_time.desc()).offset((page_num - 1) * page_size).limit(page_size)
        with session_getter() as session:
            return session.exec(statment).all()

    @classmethod
    def get_count_by_filters(cls, filters: List) -> int:
        with session_getter() as session:
            count_statement = session.query(func.count(Assistant.id))
            filters.append(Assistant.is_delete == 0)
            return session.exec(count_statement.where(*filters)).scalar()

    @classmethod
    def filter_assistant_by_id(cls, assistant_ids: List[UUID], keywords: str = None, page: int = 0,
                               limit: int = 0) -> (List[Assistant], int):
        """
        根据关键字和助手id过滤出对应的助手
        """
        statement = select(Assistant).where(Assistant.is_delete == 0)
        count_statement = select(func.count(Assistant.id)).where(Assistant.is_delete == 0)
        if assistant_ids:
            statement = statement.where(Assistant.id.in_(assistant_ids))
            count_statement = count_statement.where(Assistant.id.in_(assistant_ids))
        if keywords:
            statement = statement.where(or_(
                Assistant.name.like(f'%{keywords}%'),
                Assistant.desc.like(f'%{keywords}%')
            ))
            count_statement = count_statement.where(or_(
                Assistant.name.like(f'%{keywords}%'),
                Assistant.desc.like(f'%{keywords}%')
            ))
        if page and limit:
            statement = statement.offset((page - 1) * limit).limit(limit)
        statement.order_by(Assistant.update_time.desc())

        with session_getter() as session:
            result = session.exec(statement).all()
            return result, session.scalar(count_statement)


class AssistantLinkDao(AssistantLink):

    @classmethod
    def insert_batch(cls,
                     assistant_id: UUID,
                     tool_list: List[int] = None,
                     flow_list: List[str] = None):
        if not tool_list and not flow_list:
            return []
        with session_getter() as session:
            if tool_list:
                for one in tool_list:
                    if one == 0:
                        continue
                    session.add(AssistantLink(assistant_id=assistant_id, tool_id=one))
            if flow_list:
                for one in flow_list:
                    if not one:
                        continue
                    session.add(AssistantLink(assistant_id=assistant_id, flow_id=one))
            session.commit()

    @classmethod
    def get_assistant_link(cls, assistant_id: UUID) -> List[AssistantLink]:
        with session_getter() as session:
            statement = select(AssistantLink).where(AssistantLink.assistant_id == assistant_id)
            return session.exec(statement).all()

    @classmethod
    def update_assistant_tool(cls, assistant_id: UUID, tool_list: List[int]):
        with session_getter() as session:
            session.query(AssistantLink).filter(AssistantLink.assistant_id == assistant_id,
                                                AssistantLink.tool_id != 0).delete()
            for one in tool_list:
                if one == 0:
                    continue
                session.add(AssistantLink(assistant_id=assistant_id, tool_id=one))
            session.commit()

    @classmethod
    def update_assistant_flow(cls, assistant_id: UUID, flow_list: List[str]):
        with session_getter() as session:
            session.query(AssistantLink).filter(AssistantLink.assistant_id == assistant_id,
                                                AssistantLink.flow_id != '',
                                                AssistantLink.knowledge_id == 0).delete()
            for one in flow_list:
                if not one:
                    continue
                session.add(AssistantLink(assistant_id=assistant_id, flow_id=one))
            session.commit()

    @classmethod
    def update_assistant_knowledge(cls, assistant_id: UUID, knowledge_list: List[int],
                                   flow_id: str):
        # 保存知识库关联时必须有技能ID
        with session_getter() as session:
            session.query(AssistantLink).filter(AssistantLink.assistant_id == assistant_id,
                                                AssistantLink.knowledge_id != 0).delete()
            for one in knowledge_list:
                if one == 0:
                    continue
                session.add(
                    AssistantLink(assistant_id=assistant_id, knowledge_id=one, flow_id=flow_id))
            session.commit()
