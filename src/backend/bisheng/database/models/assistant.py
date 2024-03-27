from datetime import datetime
from enum import Enum
from typing import List, Optional

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable
from sqlalchemy import JSON, Column, DateTime, Text, func, text
from sqlmodel import Field, select


class AssistantStatus(Enum):
    OFFLINE = 0
    ONLINE = 1


class AssistantBase(SQLModelSerializable):
    id: Optional[int] = Field(nullable=False, primary_key=True, description='唯一ID')
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
    update_time: Optional[datetime] = Field(sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))


class AssistantLinkBase(SQLModelSerializable):
    id: Optional[int] = Field(nullable=False, primary_key=True, description='唯一ID')
    assistant_id: int = Field(index=True, description='助手ID')
    tool_id: Optional[int] = Field(default=0, index=True, description='工具ID')
    flow_id: Optional[str] = Field(default='', index=True, description='技能ID')
    knowledge_id: Optional[int] = Field(default=0, index=True, description='知识库ID')
    create_time: Optional[datetime] = Field(sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))


class Assistant(AssistantBase, table=True):
    pass


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
    def get_one_assistant(cls, assistant_id: int) -> Assistant:
        with session_getter() as session:
            statement = select(Assistant).where(Assistant.id == assistant_id)
            return session.exec(statement).first()

    @classmethod
    def get_assistants(cls, user_id: int, name: str, page: int, limit: int) -> (List[Assistant], int):
        with session_getter() as session:
            statement = select(Assistant).where(Assistant.user_id == user_id)
            count_statement = session.query(func.count(Assistant.id))
            if name:
                statement = statement.where(Assistant.name.like(f'%{name}%'))
                count_statement = count_statement.where(Assistant.name.like(f'%{name}%'))
            statement = statement.offset((page - 1) * limit).limit(limit).order_by(Assistant.create_time.desc())
            return session.exec(statement).all(), session.exec(count_statement).scalar()


class AssistantLinkDao(AssistantLink):

    @classmethod
    def insert_batch(cls, assistant_id: int,
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
    def update_assistant_link(cls, assistant_id: int,
                              tool_list: List[int],
                              flow_list: List[str],
                              knowledge_list: List[int]):
        with session_getter() as session:
            session.query(AssistantLink).filter(AssistantLink.assistant_id == assistant_id).delete()
            for one in tool_list:
                session.add(AssistantLink(assistant_id=assistant_id, tool_id=one))
            for one in flow_list:
                session.add(AssistantLink(assistant_id=assistant_id, flow_id=one))
            for one in knowledge_list:
                session.add(AssistantLink(assistant_id=assistant_id, knowledge_id=one))
            session.commit()

    @classmethod
    def get_assistant_link(cls, assistant_id: int) -> List[AssistantLink]:
        with session_getter() as session:
            statement = select(AssistantLink).where(AssistantLink.assistant_id == assistant_id)
            return session.exec(statement).all()

    @classmethod
    def update_assistant_tool(cls, assistant_id: int, tool_list: List[int]):
        with session_getter() as session:
            session.query(AssistantLink).filter(
                AssistantLink.assistant_id == assistant_id,
                AssistantLink.tool_id != 0).delete()
            for one in tool_list:
                session.add(AssistantLink(assistant_id=assistant_id, tool_id=one))
            session.commit()

    @classmethod
    def update_assistant_flow(cls, assistant_id: int, flow_list: List[str]):
        with session_getter() as session:
            session.query(AssistantLink).filter(
                AssistantLink.assistant_id == assistant_id,
                AssistantLink.flow_id != '').delete()
            for one in flow_list:
                session.add(AssistantLink(assistant_id=assistant_id, flow_id=one))
            session.commit()

    @classmethod
    def update_assistant_knowledge(cls, assistant_id: int, knowledge_list: List[int]):
        with session_getter() as session:
            session.query(AssistantLink).filter(
                AssistantLink.assistant_id == assistant_id,
                AssistantLink.knowledge_id != 0).delete()
            for one in knowledge_list:
                session.add(AssistantLink(assistant_id=assistant_id, knowledge_id=one))
            session.commit()
