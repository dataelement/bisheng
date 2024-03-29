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
    model_name: str = Field(default='', description='选择的模型名')
    temperature: float = Field(default=0.5, description='模型温度')
    status: int = Field(default=AssistantStatus.OFFLINE.value, description='助手是否上线')
    user_id: int = Field(default=0, description='创建用户ID')
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


class AssistantDao(Assistant):

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
            session.delete(data)
            session.commit()
            return data

    @classmethod
    def get_one_assistant(cls, assistant_id: UUID) -> Assistant:
        with session_getter() as session:
            statement = select(Assistant).where(Assistant.id == assistant_id)
            return session.exec(statement).first()

    @classmethod
    def get_assistants(cls, user_id: int, name: str, assistant_ids: List[UUID], page: int,
                       limit: int) -> (List[Assistant], int):
        with session_getter() as session:
            count_statement = session.query(func.count(Assistant.id))
            statement = select(Assistant)
            if assistant_ids:
                # 需要or 加入的条件
                statement = statement.where(
                    or_(Assistant.id.in_(assistant_ids), Assistant.user_id == user_id))
                count_statement = count_statement.where(
                    or_(Assistant.id.in_(assistant_ids), Assistant.user_id == user_id))
            else:
                statement = statement.where(Assistant.user_id == user_id)
                count_statement = count_statement.where(Assistant.user_id == user_id)

            if name:
                statement = statement.where(Assistant.name.like(f'%{name}%'))
                count_statement = count_statement.where(Assistant.name.like(f'%{name}%'))
            statement = statement.offset(
                (page - 1) * limit).limit(limit).order_by(Assistant.create_time.desc())
            return session.exec(statement).all(), session.exec(count_statement).scalar()

    @classmethod
    def get_assistants_by_access(cls, role_id: int, name: str, page_size: int,
                                 page_num: int) -> List[Tuple[Assistant, RoleAccess]]:
        statment = select(Assistant,
                          RoleAccess).join(RoleAccess,
                                           and_(RoleAccess.role_id == role_id,
                                                RoleAccess.type == AccessType.FLOW.value,
                                                RoleAccess.third_id == Assistant.id),
                                           isouter=True)

        if name:
            statment = statment.where(Assistant.name.like('%' + name + '%'))
        if page_num and page_size and page_num != 'undefined':
            page_num = int(page_num)
            statment = statment.order_by(RoleAccess.type.desc()).order_by(
                Assistant.update_time.desc()).offset((page_num - 1) * page_size).limit(page_size)
        with session_getter() as session:
            return session.exec(statment).all()

    @classmethod
    def get_count_by_filters(cls, filters) -> int:
        with session_getter() as session:
            count_statement = session.query(func.count(Assistant.id))
            return session.exec(count_statement.where(*filters)).scalar()


class AssistantLinkDao(AssistantLink):

    @classmethod
    def insert_batch(cls,
                     assistant_id: UUID,
                     tool_list: List[int] = None,
                     flow_list: List[str] = None,
                     knowledge_list: List[int] = None):
        if not tool_list and not flow_list and not knowledge_list:
            return []
        with session_getter() as session:
            if tool_list:
                for one in tool_list:
                    session.add(AssistantLink(assistant_id=assistant_id, tool_id=one))
            if flow_list:
                for one in flow_list:
                    session.add(AssistantLink(assistant_id=assistant_id, flow_id=one))
            if knowledge_list:
                for one in knowledge_list:
                    session.add(AssistantLink(assistant_id=assistant_id, knowledge_id=one))
            session.commit()

    @classmethod
    def update_assistant_link(cls, assistant_id: UUID, tool_list: List[int], flow_list: List[str],
                              knowledge_list: List[int]):
        with session_getter() as session:
            session.query(AssistantLink).filter(
                AssistantLink.assistant_id == assistant_id).delete()
            for one in tool_list:
                session.add(AssistantLink(assistant_id=assistant_id, tool_id=one))
            for one in flow_list:
                session.add(AssistantLink(assistant_id=assistant_id, flow_id=one))
            for one in knowledge_list:
                session.add(AssistantLink(assistant_id=assistant_id, knowledge_id=one))
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
                session.add(AssistantLink(assistant_id=assistant_id, tool_id=one))
            session.commit()

    @classmethod
    def update_assistant_flow(cls, assistant_id: UUID, flow_list: List[str]):
        with session_getter() as session:
            session.query(AssistantLink).filter(AssistantLink.assistant_id == assistant_id,
                                                AssistantLink.flow_id != '').delete()
            for one in flow_list:
                session.add(AssistantLink(assistant_id=assistant_id, flow_id=one))
            session.commit()

    @classmethod
    def update_assistant_knowledge(cls, assistant_id: UUID, knowledge_list: List[int]):
        with session_getter() as session:
            session.query(AssistantLink).filter(AssistantLink.assistant_id == assistant_id,
                                                AssistantLink.knowledge_id != 0).delete()
            for one in knowledge_list:
                session.add(AssistantLink(assistant_id=assistant_id, knowledge_id=one))
            session.commit()
