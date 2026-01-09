from datetime import datetime
from typing import Optional, List

from sqlalchemy import Column, DateTime, String, UniqueConstraint, delete, text
from sqlmodel import Field, select, col

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_async_db_session


class ModelDeployBase(SQLModelSerializable):
    endpoint: str = Field(index=False, unique=False)
    server: str = Field(index=True)
    model: str = Field(index=False)
    config: Optional[str] = Field(default=None, sa_column=Column(String(length=512)))
    status: Optional[str] = Field(default=None, index=False)
    remark: Optional[str] = Field(default=None, sa_column=Column(String(length=4096)))

    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))


class ModelDeploy(ModelDeployBase, table=True):
    __table_args__ = (UniqueConstraint('model', 'server', name='model_server_uniq'),)
    id: Optional[int] = Field(default=None, primary_key=True)


class ModelDeployDao(ModelDeployBase):

    @classmethod
    async def find_model(cls, model_id: int) -> ModelDeploy | None:
        async with get_async_db_session() as session:
            statement = select(ModelDeploy).where(ModelDeploy.id == model_id)
            return (await session.exec(statement)).first()

    @classmethod
    async def find_model_by_server(cls, server_id: str) -> List[ModelDeploy]:
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
            statement = delete(ModelDeploy).where(col(ModelDeploy.id) == model_id)
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
    id: Optional[int]


class ModelDeployQuery(SQLModelSerializable):
    id: Optional[int]
    server: Optional[str]


class ModelDeployCreate(ModelDeployBase):
    pass


class ModelDeployUpdate(SQLModelSerializable):
    id: int
    config: Optional[str] = None


class ModelDeployInfo(ModelDeploy):
    sft_support: bool = Field(default=False, description='Whether to support fine-tuning training')
