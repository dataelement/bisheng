from datetime import datetime
from enum import Enum
from typing import List, Optional, Tuple
from uuid import UUID, uuid4

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable
from bisheng.database.models.role_access import AccessType, RoleAccess
from sqlalchemy import JSON, Column, DateTime, Text, and_, func, or_, text
from sqlmodel import Field, select


class LlmServerBase(SQLModelSerializable):
    id: Optional[UUID] = Field(nullable=False, primary_key=True, description='唯一ID')
    name: str = Field(default='', description='服务名称')
    desc: str = Field(default='', sa_column=Column(Text), description='服务描述')
    create_time: Optional[datetime] = Field(sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=False,
                         server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))


class LlmModelBase(SQLModelSerializable):
    id: Optional[UUID] = Field(nullable=False, primary_key=True, description='唯一ID')
    name: str = Field(default='', description='模型名称')
    desc: str = Field(default='', sa_column=Column(Text), description='模型描述')
    create_time: Optional[datetime] = Field(sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=False,
                         server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))
