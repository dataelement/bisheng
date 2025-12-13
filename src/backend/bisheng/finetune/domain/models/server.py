from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, text, delete
from sqlmodel import Field, select, col

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_async_db_session


class ServerBase(SQLModelSerializable):
    endpoint: str = Field(index=False)
    sft_endpoint: str = Field(default='', index=False, description='Finetune服务地址')
    server: str = Field(index=True)
    remark: Optional[str] = Field(default=None, index=False)
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))


class Server(ServerBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)


# 封装业务操作
class ServerDao(ServerBase):
    @classmethod
    async def find_server(cls, server_id: int) -> Server | None:
        async with get_async_db_session() as session:
            statement = select(Server).where(Server.id == server_id)
            return (await session.exec(statement)).first()

    @classmethod
    async def find_all_server(cls):
        async with get_async_db_session() as session:
            statement = select(Server)
            return (await session.exec(statement)).all()

    @classmethod
    async def insert(cls, server: Server) -> Server:
        async with get_async_db_session() as session:
            session.add(server)
            await session.commit()
            await session.refresh(server)
            return server

    @classmethod
    async def delete(cls, server_id: int) -> None:
        statement = delete(Server).where(col(Server.id) == server_id)
        async with get_async_db_session() as session:
            await session.exec(statement)
            await session.commit()


class ServerRead(ServerBase):
    id: Optional[int] = None


class ServerQuery(ServerBase):
    id: Optional[int] = None
    server: Optional[str] = None


class ServerCreate(ServerBase):
    pass
