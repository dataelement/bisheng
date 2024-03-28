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
    ASSITANT_READ = 5


class RoleRefresh(BaseModel):
    role_id: int
    access_id: list[Union[str, int]]
    type: int


class RoleAcessDao(RoleAccessBase):

    @classmethod
    def get_role_acess(cls, role_ids: List[int], access_type: AccessType) -> List[RoleAccess]:
        with session_getter() as session:
            if access_type:
                return session.exec(
                    select(RoleAccess).where(RoleAccess.role_id.in_(role_ids),
                                             RoleAccess.type == access_type.value)).all()
            return session.exec(select(RoleAccess).where(RoleAccess.role_id.in_(role_ids))).all()
