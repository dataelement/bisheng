from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint, delete, text
from sqlmodel import Field, col, select

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT
from bisheng.finetune.domain.repositories.session import get_finetune_session as get_async_db_session


class ModelDeployBase(SQLModelSerializable):
    endpoint: str = Field(index=False, unique=False)
    server: str = Field(index=True)
    model: str = Field(index=False)
    config: str | None = Field(default=None, sa_column=Column(String(length=512)))
    status: str | None = Field(default=None, index=False)
    remark: str | None = Field(default=None, sa_column=Column(String(length=4096)))
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, nullable=False, server_default=text("1"), index=True, comment="Tenant ID"),
    )

    create_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    )
    update_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT)
    )


class ModelDeploy(ModelDeployBase, table=True):
    __table_args__ = (UniqueConstraint("model", "server", name="model_server_uniq"),)
    id: int | None = Field(default=None, primary_key=True)


class ModelDeployDao(ModelDeployBase):
    @classmethod
    async def find_model(cls, model_id: int) -> ModelDeploy | None:
        async with get_async_db_session() as session:
            statement = select(ModelDeploy).where(ModelDeploy.id == model_id)
            return (await session.exec(statement)).first()

    @classmethod
    async def find_model_by_server(cls, server_id: str) -> list[ModelDeploy]:
        async with get_async_db_session() as session:
            statement = select(ModelDeploy).where(ModelDeploy.server == server_id)
            return (await session.exec(statement)).all()

    @classmethod
    async def find_model_by_server_and_name(cls, server: str, model: str) -> ModelDeploy | None:
        async with get_async_db_session() as session:
            statement = select(ModelDeploy).where(ModelDeploy.server == server, ModelDeploy.model == model)
            return (await session.exec(statement)).first()

    @classmethod
    async def find_model_by_name(cls, model: str) -> ModelDeploy | None:
        async with get_async_db_session() as session:
            statement = select(ModelDeploy).where(ModelDeploy.model == model)
            return (await session.exec(statement)).first()

    @classmethod
    async def delete_model(cls, model: ModelDeploy) -> bool:
        async with get_async_db_session() as session:
            await session.delete(model)
            await session.commit()
        return True

    @classmethod
    async def delete_model_by_id(cls, model_id: int):
        async with get_async_db_session() as session:
            statement = delete(ModelDeploy).where(
                col(ModelDeploy.id) == model_id, col(ModelDeploy.tenant_id) == get_current_tenant_id()
            )
            await session.exec(statement)
            await session.commit()

    @classmethod
    async def insert_one(cls, model: ModelDeploy) -> ModelDeploy:
        async with get_async_db_session() as session:
            session.add(model)
            await session.commit()
            await session.refresh(model)
        return model

    @classmethod
    async def update_model(cls, model: ModelDeploy) -> ModelDeploy:
        async with get_async_db_session() as session:
            session.add(model)
            await session.commit()
            await session.refresh(model)
        return model


class ModelDeployRead(ModelDeployBase):
    id: int | None


class ModelDeployQuery(SQLModelSerializable):
    id: int | None
    server: str | None


class ModelDeployCreate(ModelDeployBase):
    pass


class ModelDeployUpdate(SQLModelSerializable):
    id: int
    config: str | None = None


class ModelDeployInfo(ModelDeploy):
    sft_support: bool = Field(default=False, description="Whether to support fine-tuning training")
