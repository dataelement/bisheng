from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, text
from sqlmodel import Field, select

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable


class ServerBase(SQLModelSerializable):
    endpoint: str = Field(index=False)
    sft_endpoint: str = Field(default='', index=False, description='Finetune服务地址')
    server: str = Field(index=True)
    remark: Optional[str] = Field(default=None, index=False)
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP'), onupdate=text('CURRENT_TIMESTAMP')))


class Server(ServerBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)


# 封装业务操作
class ServerDao(ServerBase):
    @classmethod
    def find_server(cls, server_id: int) -> Server | None:
        with session_getter() as session:
            statement = select(Server).where(Server.id == server_id)
            return session.exec(statement).first()

    @classmethod
    def find_all_server(cls):
        with session_getter() as session:
            statement = select(Server)
            return session.exec(statement).all()


class ServerRead(ServerBase):
    id: Optional[int] = None


class ServerQuery(ServerBase):
    id: Optional[int] = None
    server: Optional[str] = None


class ServerCreate(ServerBase):
    pass
