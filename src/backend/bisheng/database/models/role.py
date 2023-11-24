from datetime import datetime
from typing import Optional

from bisheng.database.models.base import SQLModelSerializable
from sqlalchemy import Column, DateTime, text
from sqlmodel import Field


class RoleBase(SQLModelSerializable):
    role_name: str = Field(index=False, description='前端展示名称', unique=True)
    remark: Optional[str] = Field(index=False)
    create_time: Optional[datetime] = Field(sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=False,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')))


class Role(RoleBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)


class RoleRead(RoleBase):
    id: Optional[int]


class RoleUpdate(RoleBase):
    role_name: Optional[str]
    remark: Optional[str]


class RoleCreate(RoleBase):
    pass
