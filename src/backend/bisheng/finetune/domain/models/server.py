from datetime import datetime

from pydantic import field_validator
from sqlalchemy import Column, DateTime, Integer, delete, text
from sqlmodel import Field, col, select

from bisheng.common.errcode.tenant import NoTenantContextError
from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.context.tenant import bypass_tenant_filter, get_current_tenant_id, strict_tenant_filter
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
    def _scope_tenant(cls, tenant_id: int | None) -> int:
        if tenant_id is None:
            tenant_id = get_current_tenant_id()
        if isinstance(tenant_id, bool) or not isinstance(tenant_id, int) or tenant_id <= 0:
            raise NoTenantContextError()
        return tenant_id

    @classmethod
    async def find_server(cls, server_id: int) -> Server | None:
        async with get_async_db_session() as session:
            statement = select(Server).where(Server.id == server_id)
            with strict_tenant_filter():
                return (await session.exec(statement)).first()

    @classmethod
    async def find_all_server(cls):
        async with get_async_db_session() as session:
            statement = select(Server)
            with strict_tenant_filter():
                return (await session.exec(statement)).all()

    @classmethod
    async def find_sft_owners(cls) -> list[tuple[int, str]]:
        # Ownership proof only: FT has no tenant namespace. Never return this
        # cross-tenant inventory to API callers or use it to widen task reads.
        async with get_async_db_session() as session:
            with bypass_tenant_filter():
                return list((await session.exec(select(Server.tenant_id, Server.sft_endpoint))).all())

    @classmethod
    async def insert(cls, server: Server, *, tenant_id: int | None = None) -> Server:
        # Ownership is supplied only by the authorized service scope.
        server.tenant_id = cls._scope_tenant(tenant_id)
        async with get_async_db_session() as session:
            session.add(server)
            await session.commit()
            await session.refresh(server)
            return server

    @classmethod
    async def delete(cls, server_id: int, *, tenant_id: int | None = None) -> bool:
        # Bulk DELETE is not covered by the SELECT-only tenant event.
        tenant_id = cls._scope_tenant(tenant_id)
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

    @field_validator("sft_endpoint")
    @classmethod
    def validate_ft_endpoint(cls, value):
        from bisheng.finetune.utils import parse_server_host

        return parse_server_host(value) if value else value
