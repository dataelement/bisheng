from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import Column, DateTime, Integer, delete, text
from sqlmodel import Field, col, select

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT
from bisheng.finetune.domain.repositories.session import get_finetune_session as get_async_db_session


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
    async def insert(cls, server: Server) -> Server:
        async with get_async_db_session() as session:
            session.add(server)
            await session.commit()
            await session.refresh(server)
            return server

    @classmethod
    async def delete(cls, server_id: int) -> None:
        statement = delete(Server).where(col(Server.id) == server_id, col(Server.tenant_id) == get_current_tenant_id())
        async with get_async_db_session() as session:
            await session.exec(statement)
            await session.commit()


class ServerRead(ServerBase):
    id: int | None = None


class ServerQuery(ServerBase):
    id: int | None = None
    server: str | None = None


class ServerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    server: str = Field(min_length=1, max_length=255)
    endpoint: str = ""
    sft_endpoint: str = ""
    remark: str | None = None

    @field_validator("sft_endpoint")
    @classmethod
    def validate_ft_endpoint(cls, value):
        from bisheng.finetune.utils import parse_server_host

        return parse_server_host(value) if value else value
