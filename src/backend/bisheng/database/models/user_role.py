from datetime import datetime
from typing import Optional

from bisheng.database.models.base import SQLModelSerializable
from pydantic import BaseModel
from sqlalchemy import Column, DateTime, text
from sqlmodel import Field


class UserRoleBase(SQLModelSerializable):
    user_id: int = Field(index=True)
    role_id: int = Field(index=True)
    create_time: Optional[datetime] = Field(
        sa_column=Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=False,
                         index=True,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')))


class UserRole(UserRoleBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)


class UserRoleRead(UserRoleBase):
    id: Optional[int]


class UserRoleCreate(BaseModel):
    user_id: int
    role_id: list[int]
