from datetime import datetime
from typing import Optional

from bisheng.database.models.base import SQLModelSerializable
from sqlalchemy import Column, DateTime, String, text
from sqlmodel import Field


class ServerBase(SQLModelSerializable):
    endpoint: str = Field(index=False, unique=True)
    server: str = Field(index=True)
    remark: Optional[str] = Field(index=False)
    gpu: Optional[str] = Field(index=False, sa_column=Column(String(length=1024)))
    create_time: Optional[datetime] = Field(
        sa_column=Column(DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP'), onupdate=text('CURRENT_TIMESTAMP')))


class Server(ServerBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)


class ServerRead(ServerBase):
    id: Optional[int]


class ServerQuery(ServerBase):
    id: Optional[int]
    server: Optional[str]


class ServerCreate(ServerBase):
    pass
