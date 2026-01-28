from datetime import datetime
from enum import Enum
from typing import List, Optional, Union

from pydantic import BaseModel
from sqlalchemy import Column, DateTime, text
from sqlmodel import Field, select, delete, col

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_sync_db_session, get_async_db_session


class RoleAccessBase(SQLModelSerializable):
    role_id: int = Field(index=True)
    third_id: str = Field(index=False)
    type: int = Field(index=False)
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))


class RoleAccess(RoleAccessBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)


class RoleAccessRead(RoleAccessBase):
    id: Optional[int] = None


class RoleAccessCreate(RoleAccessBase):
    pass


class WebMenuResource(Enum):
    """Front-end menu bar resources"""

    BUILD = 'build'  # Build Menu
    KNOWLEDGE = 'knowledge'  # Knowledge Menu
    MODEL = 'model'  # Model Menu
    EVALUATION = 'evaluation'  # Evaluation Menu

    FRONTEND = 'frontend'  # Front-end permissions
    BACKEND = 'backend'  # Backend Access

    CREATE_DASHBOARD = 'create_dashboard'  # Create board permissions


class AccessType(Enum):
    """Type of the role_access"""

    KNOWLEDGE = 1  # Knowledge Base Reading Permissions
    FLOW = 2  # Skill Read Permissions
    KNOWLEDGE_WRITE = 3  # Knowledge Base Write Permissions
    FLOW_WRITE = 4  # Skill Write Permissions
    ASSISTANT_READ = 5  # Assistant Read Permissions
    ASSISTANT_WRITE = 6  # Assistant Write Permissions
    GPTS_TOOL_READ = 7  # Tool Read Permissions
    GPTS_TOOL_WRITE = 8  # Tool Write Permissions
    WORKFLOW = 9  # Workflow Read Permissions
    WORKFLOW_WRITE = 10  # Workflow write permissions
    DASHBOARD = 11  # Kanban Reading Permissions
    DASHBOARD_WRITE = 12  # Kanban writing permissions

    WEB_MENU = 99  # Frontend Menu Bar Permission Restrictions


class RoleRefresh(BaseModel):
    role_id: int
    access_id: list[Union[str, int]]
    type: int


class RoleAccessDao(RoleAccessBase):

    @classmethod
    def get_role_access(cls, role_ids: List[int], access_type: AccessType) -> List[RoleAccess]:
        with get_sync_db_session() as session:
            if access_type:
                return session.exec(
                    select(RoleAccess).where(RoleAccess.role_id.in_(role_ids),
                                             RoleAccess.type == access_type.value)).all()
            return session.exec(select(RoleAccess).where(RoleAccess.role_id.in_(role_ids))).all()

    @classmethod
    async def aget_role_access(cls, role_ids: List[int], access_type: AccessType = None) -> List[RoleAccess]:
        statement = select(RoleAccess).where(RoleAccess.role_id.in_(role_ids))
        if access_type:
            statement = statement.where(RoleAccess.type == access_type.value)

        async with get_async_db_session() as session:
            return (await session.exec(statement)).all()

    @classmethod
    def get_role_access_batch(cls, role_ids: List[int], access_type: List[AccessType]) -> List[RoleAccess]:
        with get_sync_db_session() as session:
            if access_type:
                return session.exec(
                    select(RoleAccess).where(RoleAccess.role_id.in_(role_ids),
                                             RoleAccess.type.in_([x.value for x in access_type]))).all()

    @classmethod
    async def aget_role_access_batch(cls, role_ids: List[int], access_type: List[AccessType]) -> List[RoleAccess]:
        statement = select(RoleAccess).where(col(RoleAccess.role_id).in_(role_ids))
        if access_type:
            statement = statement.where(col(RoleAccess.type).in_([x.value for x in access_type]))

        async with get_async_db_session() as session:
            return (await session.exec(statement)).all()

    @classmethod
    def judge_role_access(cls, role_ids: List[int], third_id: str, access_type: AccessType) -> Optional[RoleAccess]:
        with get_sync_db_session() as session:
            return session.exec(select(RoleAccess).filter(
                RoleAccess.role_id.in_(role_ids),
                RoleAccess.type == access_type.value,
                RoleAccess.third_id == third_id
            )).first()

    @classmethod
    async def ajudge_role_access(cls, role_ids: List[int], third_id: str, access_type: AccessType) -> Optional[
        RoleAccess]:
        statement = select(RoleAccess).filter(
            col(RoleAccess.role_id).in_(role_ids),
            col(RoleAccess.type) == access_type.value,
            col(RoleAccess.third_id) == third_id
        )
        async with get_async_db_session() as session:
            return (await session.exec(statement)).first()

    @classmethod
    def find_role_access(cls, role_ids: List[int], third_ids: List[str], access_type: AccessType) -> List[RoleAccess]:
        with get_sync_db_session() as session:
            if access_type:
                return session.exec(
                    select(RoleAccess).where(RoleAccess.role_id.in_(role_ids),
                                             RoleAccess.third_id.in_(third_ids),
                                             RoleAccess.type == access_type.value)).all()
            return session.exec(select(RoleAccess).where(RoleAccess.role_id.in_(role_ids))).all()

    @classmethod
    async def afind_role_access(cls, role_ids: List[int], third_ids: List[str], access_type: AccessType) -> List[
        RoleAccess]:
        statement = select(RoleAccess).where(
            col(RoleAccess.role_id).in_(role_ids),
            col(RoleAccess.third_id).in_(third_ids)
        )
        if access_type:
            statement = statement.where(col(RoleAccess.type) == access_type.value)
        async with get_async_db_session() as session:
            return (await session.exec(statement)).all()

    @classmethod
    async def update_role_access_all(cls, role_id: int, access_type: AccessType,
                                     access_ids: List[Union[str, int]]) -> None:
        """
        Update the role's permissions, delete it first and add it later
        """
        async with get_async_db_session() as session:
            # Clear all old permissions first
            statement = delete(RoleAccess).where(col(RoleAccess.role_id) == str(role_id),
                                                 col(RoleAccess.type) == access_type.value)
            await session.exec(statement)
            # Add New Permission
            for access_id in access_ids:
                role_access = RoleAccess(role_id=role_id, third_id=str(access_id), type=access_type.value)
                session.add(role_access)
            await session.commit()
