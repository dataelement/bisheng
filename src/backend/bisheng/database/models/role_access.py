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


class AccessType(Enum):
    """Type of the role_access"""

    KNOWLEDGE = 1  # 知识库读权限
    FLOW = 2  # 技能读权限
    KNOWLEDGE_WRITE = 3  # 知识库写权限
    FLOW_WRITE = 4  # 技能写权限
    ASSISTANT_READ = 5  # 助手读权限
    ASSISTANT_WRITE = 6  # 助手写权限
    GPTS_TOOL_READ = 7  # 工具读权限
    GPTS_TOOL_WRITE = 8  # 工具写权限
    WORKFLOW = 9  # 工作流读权限
    WORKFLOW_WRITE = 10  # 工作流写权限

    WEB_MENU = 99  # 前端菜单栏权限限制


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
        更新角色的权限，先删除后添加
        """
        async with get_async_db_session() as session:
            # 先把旧的权限全部清空
            statement = delete(RoleAccess).where(col(RoleAccess.role_id) == str(role_id),
                                                 col(RoleAccess.type) == access_type.value)
            await session.exec(statement)
            # 添加新的权限
            for access_id in access_ids:
                role_access = RoleAccess(role_id=role_id, third_id=str(access_id), type=access_type.value)
                session.add(role_access)
            await session.commit()
