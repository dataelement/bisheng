from datetime import datetime
from typing import Optional

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable
from sqlalchemy import Column, DateTime, text
from sqlmodel import Field, select


class ServerBase(SQLModelSerializable):
    endpoint: str = Field(index=False, unique=True)
    sft_endpoint: str = Field(default='', index=False, description='Finetune服务地址')
    server: str = Field(index=True)
    remark: Optional[str] = Field(index=False)
    create_time: Optional[datetime] = Field(sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=False,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')))


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
    id: Optional[int]


class ServerQuery(ServerBase):
    id: Optional[int]
    server: Optional[str]


class ServerCreate(ServerBase):
    pass
