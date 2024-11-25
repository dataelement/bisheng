from datetime import datetime
from enum import Enum
from typing import List, Optional, Union

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable
from pydantic import BaseModel
from sqlalchemy import Column, DateTime, text
from sqlmodel import Field, select


class RoleAccessBase(SQLModelSerializable):
    role_id: str = Field(index=True)
    third_id: str = Field(index=False)
    type: int = Field(index=False)
    create_time: Optional[datetime] = Field(
        sa_column=Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=False,
                         index=True,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')))


class RoleAccess(RoleAccessBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)


class RoleAccessRead(RoleAccessBase):
    id: Optional[int]


class RoleAccessCreate(RoleAccessBase):
    pass


class AccessType(Enum):
    """Type of the role_access"""

    KNOWLEDGE = 1
    FLOW = 2
    KNOWLEDGE_WRITE = 3
    FLOW_WRITE = 4
    ASSISTANT_READ = 5
    ASSISTANT_WRITE = 6
    GPTS_TOOL_READ = 7
    GPTS_TOOL_WRITE = 8
    WORK_FLOW= 9
    WORK_FLOW_WRITE= 10

    WEB_MENU = 99  # 前端菜单栏权限限制


class RoleRefresh(BaseModel):
    role_id: int
    access_id: list[Union[str, int]]
    type: int


class RoleAccessDao(RoleAccessBase):

    @classmethod
    def get_role_access(cls, role_ids: List[int], access_type: AccessType) -> List[RoleAccess]:
        with session_getter() as session:
            if access_type:
                return session.exec(
                    select(RoleAccess).where(RoleAccess.role_id.in_(role_ids),
                                             RoleAccess.type == access_type.value)).all()
            return session.exec(select(RoleAccess).where(RoleAccess.role_id.in_(role_ids))).all()

    @classmethod
    def judge_role_access(cls, role_ids: List[int], third_id: str, access_type: AccessType) -> Optional[RoleAccess]:
        with session_getter() as session:
            return session.exec(select(RoleAccess).filter(
                RoleAccess.role_id.in_(role_ids),
                RoleAccess.type == access_type.value,
                RoleAccess.third_id == third_id
            )).first()

    @classmethod
    def find_role_access(cls, role_ids: List[int], third_ids: List[str], access_type: AccessType) -> List[RoleAccess]:
        with session_getter() as session:
            if access_type:
                return session.exec(
                    select(RoleAccess).where(RoleAccess.role_id.in_(role_ids),
                                             RoleAccess.third_id.in_(third_ids),
                                             RoleAccess.type == access_type.value)).all()
            return session.exec(select(RoleAccess).where(RoleAccess.role_id.in_(role_ids))).all()
