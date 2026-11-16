from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, delete, text
from sqlmodel import Field, col, select

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_async_db_session
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT


class ServerBase(SQLModelSerializable):
    endpoint: str = Field(index=False)
    sft_endpoint: str = Field(default="", index=False, description="FinetuneService Address")
    server: str = Field(index=True)
    remark: str | None = Field(default=None, index=False)
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, nullable=False, server_default=text("1"), index=True, comment="Tenant ID"),
    )
    create_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, index=True, server_default=text("CURRENT_TIMESTAMP"))
    )
    update_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT)
    )


class Server(ServerBase, table=True):
    id: int | None = Field(default=None, primary_key=True)


# Package business operations
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
    async def insert(cls, server: Server, *, tenant_id: int) -> Server:
        # Ownership is supplied only by the authorized service scope.
        server.tenant_id = tenant_id
        async with get_async_db_session() as session:
            session.add(server)
            await session.commit()
            await session.refresh(server)
            return server

    @classmethod
    async def delete(cls, server_id: int, *, tenant_id: int) -> bool:
        # Bulk DELETE is not covered by the SELECT-only tenant event.
        statement = delete(Server).where(col(Server.id) == server_id, col(Server.tenant_id) == tenant_id)
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            await session.commit()
            return result.rowcount > 0


class ServerRead(ServerBase):
    id: int | None = None


class ServerQuery(ServerBase):
    id: int | None = None
    server: str | None = None


class ServerCreate(SQLModelSerializable):
    """Client-editable connection fields, never tenant or persistence ownership."""

    endpoint: str
    sft_endpoint: str = ""
    server: str
    remark: str | None = None
