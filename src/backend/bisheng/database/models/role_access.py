from datetime import datetime
from enum import Enum
from typing import Optional, Union

from bisheng.database.models.base import SQLModelSerializable
from pydantic import BaseModel
from sqlalchemy import Column, DateTime, text
from sqlmodel import Field


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


class RoleRefresh(BaseModel):
    role_id: int
    access_id: list[Union[str, int]]
    type: int
