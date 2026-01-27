from datetime import datetime
from enum import Enum
from typing import List, Optional, Tuple

from sqlalchemy import JSON, Column, DateTime, Text, and_, func, or_, text
from sqlmodel import Field, select, col

from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum
from bisheng.common.models.base import SQLModelSerializable
from bisheng.common.services import telemetry_service
from bisheng.core.database import get_sync_db_session, get_async_db_session
from bisheng.core.logger import trace_id_var
from bisheng.database.models.role_access import AccessType, RoleAccess
from bisheng.utils import generate_uuid


class AssistantStatus(Enum):
    OFFLINE = 1
    ONLINE = 2


class AssistantBase(SQLModelSerializable):
    id: Optional[str] = Field(default_factory=generate_uuid, nullable=False, primary_key=True,
                              description='Uniqueness quantificationID')
    name: str = Field(default='', description='The assistant name.')
    logo: str = Field(default='', description='logoimage URL')
    desc: str = Field(default='', sa_column=Column(Text), description='Assistant description')
    system_prompt: str = Field(default='', sa_column=Column(Text), description='System Prompt')
    prompt: str = Field(default='', sa_column=Column(Text), description='User Visible Descriptor')
    guide_word: Optional[str] = Field(default='', sa_column=Column(Text), description='Ice Breaker ')
    guide_question: Optional[List] = Field(default_factory=list, sa_column=Column(JSON),
                                           description='Facilitation Questions')
    model_name: str = Field(default='', description='Corresponds to the only model in the model managementID')
    temperature: float = Field(default=0.5, description='Model Temperature')
    max_token: int = Field(default=32000, description='MaxtokenQuantity')
    status: int = Field(default=AssistantStatus.OFFLINE.value, description='Whether the assistant is online')
    user_id: int = Field(default=0, description='Create UserID')
    is_delete: int = Field(default=0, description='Remove logo')
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))


class AssistantLinkBase(SQLModelSerializable):
    id: Optional[int] = Field(default=None, nullable=False, primary_key=True, description='Uniqueness quantificationID')
    assistant_id: Optional[str] = Field(default=0, index=True, description='assistantID')
    tool_id: Optional[int] = Field(default=0, index=True, description='ToolsID')
    flow_id: Optional[str] = Field(default='', index=True, description='SkillID')
    knowledge_id: Optional[int] = Field(default=0, index=True, description='The knowledge base uponID')
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))


class Assistant(AssistantBase, table=True):
    id: str = Field(default_factory=generate_uuid, primary_key=True, unique=True)


class AssistantLink(AssistantLinkBase, table=True):
    pass


class AssistantDao(AssistantBase):

    @classmethod
    def create_assistant(cls, data: Assistant) -> Assistant:
        with get_sync_db_session() as session:
            session.add(data)
            session.commit()
            session.refresh(data)
            return data

    @classmethod
    def update_assistant(cls, data: Assistant) -> Assistant:
        with get_sync_db_session() as session:
            session.add(data)
            session.commit()
            session.refresh(data)
            return data

    @classmethod
    def delete_assistant(cls, data: Assistant) -> Assistant:
        with get_sync_db_session() as session:
            data.is_delete = 1
            session.add(data)
            session.commit()
            session.refresh(data)
            return data

    @classmethod
    def get_one_assistant(cls, assistant_id: str) -> Assistant:
        with get_sync_db_session() as session:
            statement = select(Assistant).where(Assistant.id == assistant_id)
            return session.exec(statement).first()

    @classmethod
    async def aget_one_assistant(cls, assistant_id: str) -> Assistant:
        statement = select(Assistant).where(Assistant.id == assistant_id)
        async with get_async_db_session() as session:
            return (await session.exec(statement)).first()

    @classmethod
    def get_assistants_by_ids(cls, assistant_ids: List[str]) -> List[Assistant]:
        if not assistant_ids:
            return []
        with get_sync_db_session() as session:
            statement = select(Assistant).where(Assistant.id.in_(assistant_ids))
            return session.exec(statement).all()

    @classmethod
    async def aget_assistants_by_ids(cls, assistant_ids: List[str]) -> List[Assistant]:
        if not assistant_ids:
            return []
        statement = select(Assistant).where(col(Assistant.id).in_(assistant_ids))
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    def get_assistant_by_name_user_id(cls, name: str, user_id: int) -> Assistant:
        with get_sync_db_session() as session:
            statement = select(Assistant).filter(Assistant.name == name,
                                                 Assistant.user_id == user_id,
                                                 Assistant.is_delete == 0)
            return session.exec(statement).first()

    @classmethod
    def get_assistants(cls, user_id: int, name: str, assistant_ids_extra: List[str],
                       status: Optional[int], page: int, limit: int, assistant_ids: List[str] = None) -> (
            List[Assistant], int):
        with get_sync_db_session() as session:
            count_statement = session.query(func.count(
                Assistant.id)).where(Assistant.is_delete == 0)
            statement = select(Assistant).where(Assistant.is_delete == 0)
            if assistant_ids_extra:
                # Membutuhkanor Requirements to join
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
                # Get all, no pagination
                statement = statement.order_by(Assistant.update_time.desc())
            else:
                statement = statement.offset(
                    (page - 1) * limit).limit(limit).order_by(Assistant.update_time.desc())
            return session.exec(statement).all(), session.exec(count_statement).scalar()

    @classmethod
    def get_all_online_assistants(cls, flow_ids: List[str]) -> List[Assistant]:
        """ Get all live assistants """
        statement = select(Assistant).filter(Assistant.status == AssistantStatus.ONLINE.value,
                                             Assistant.is_delete == 0)
        if flow_ids:
            statement = statement.where(Assistant.flow_id.in_(flow_ids))
        statement = statement.order_by(Assistant.update_time.desc())
        with get_sync_db_session() as session:
            return session.exec(statement).all()

    @classmethod
    def get_all_assistants(cls, name: str, page: int, limit: int, assistant_ids: List[str] = None,
                           status: int = None) -> (List[Assistant], int):
        with get_sync_db_session() as session:
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
        with get_sync_db_session() as session:
            return session.exec(statment).all()

    @classmethod
    def get_count_by_filters(cls, filters: List) -> int:
        with get_sync_db_session() as session:
            count_statement = session.query(func.count(Assistant.id))
            filters.append(Assistant.is_delete == 0)
            return session.exec(count_statement.where(*filters)).scalar()

    @classmethod
    def filter_assistant_by_id(cls, assistant_ids: List[str], keywords: str = None, page: int = 0,
                               limit: int = 0) -> (List[Assistant], int):
        """
        Based on keywords and assistantsidFilter out corresponding assistants
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
        statement = statement.order_by(Assistant.update_time.desc())

        with get_sync_db_session() as session:
            result = session.exec(statement).all()
            return result, session.scalar(count_statement)


class AssistantLinkDao(AssistantLink):

    @classmethod
    def insert_batch(cls,
                     assistant_id: str,
                     tool_list: List[int] = None,
                     flow_list: List[str] = None):
        if not tool_list and not flow_list:
            return []
        with get_sync_db_session() as session:
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
    async def get_assistant_link(cls, assistant_id: str) -> List[AssistantLink]:
        async with get_async_db_session() as session:
            statement = select(AssistantLink).where(AssistantLink.assistant_id == assistant_id)
            result = await session.exec(statement)
            return result.all()

    @classmethod
    def update_assistant_tool(cls, assistant_id: str, tool_list: List[int]):
        with get_sync_db_session() as session:
            session.query(AssistantLink).filter(AssistantLink.assistant_id == assistant_id,
                                                AssistantLink.tool_id != 0).delete()
            for one in tool_list:
                if one == 0:
                    continue
                session.add(AssistantLink(assistant_id=assistant_id, tool_id=one))
            session.commit()

    @classmethod
    def update_assistant_flow(cls, assistant_id: str, flow_list: List[str]):
        with get_sync_db_session() as session:
            session.query(AssistantLink).filter(AssistantLink.assistant_id == assistant_id,
                                                AssistantLink.flow_id != '',
                                                AssistantLink.knowledge_id == 0).delete()
            for one in flow_list:
                if not one:
                    continue
                session.add(AssistantLink(assistant_id=assistant_id, flow_id=one))
            session.commit()

    @classmethod
    def update_assistant_knowledge(cls, assistant_id: str, knowledge_list: List[int],
                                   flow_id: str):
        # Must have skills when saving knowledge base associationsID
        with get_sync_db_session() as session:
            session.query(AssistantLink).filter(AssistantLink.assistant_id == assistant_id,
                                                AssistantLink.knowledge_id != 0).delete()
            for one in knowledge_list:
                if one == 0:
                    continue
                session.add(
                    AssistantLink(assistant_id=assistant_id, knowledge_id=one, flow_id=flow_id))
            session.commit()
