from datetime import datetime
from typing import Optional

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable
from sqlalchemy import Column, DateTime, String, UniqueConstraint, delete, text
from sqlmodel import Field, select


class ModelDeployBase(SQLModelSerializable):
    endpoint: str = Field(index=False, unique=False)
    server: str = Field(index=True)
    model: str = Field(index=False)
    config: Optional[str] = Field(sa_column=Column(String(length=512)))
    status: Optional[str] = Field(index=False)
    remark: Optional[str] = Field(sa_column=Column(String(length=4096)))

    create_time: Optional[datetime] = Field(
        sa_column=Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=False,
                         index=True,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')))


class ModelDeploy(ModelDeployBase, table=True):
    __table_args__ = (UniqueConstraint('model', 'server', name='model_server_uniq'),)
    id: Optional[int] = Field(default=None, primary_key=True)


class ModelDeployDao(ModelDeployBase):

    @classmethod
    def find_model(cls, model_id: int) -> ModelDeploy | None:
        with session_getter() as session:
            statement = select(ModelDeploy).where(ModelDeploy.id == model_id)
            return session.exec(statement).first()

    @classmethod
    def find_model_by_server_and_name(cls, server: str, model: str) -> ModelDeploy | None:
        with session_getter() as session:
            statement = select(ModelDeploy).where(ModelDeploy.server == server, ModelDeploy.model == model)
            return session.exec(statement).first()

    @classmethod
    def find_model_by_name(cls, model: str) -> ModelDeploy | None:
        with session_getter() as session:
            statement = select(ModelDeploy).where(ModelDeploy.model == model)
            return session.exec(statement).first()

    @classmethod
    def delete_model(cls, model: ModelDeploy) -> bool:
        with session_getter() as session:
            session.delete(model)
            session.commit()
        return True

    @classmethod
    def delete_model_by_id(cls, model_id: int):
        with session_getter() as session:
            statement = delete(ModelDeploy).where(ModelDeploy.id == model_id)
            session.exec(statement)
            session.commit()

    @classmethod
    def insert_one(cls, model: ModelDeploy) -> ModelDeploy:
        with session_getter() as session:
            session.add(model)
            session.commit()
            session.refresh(model)
        return model

    @classmethod
    def update_model(cls, model: ModelDeploy) -> ModelDeploy:
        with session_getter() as session:
            session.add(model)
            session.commit()
            session.refresh(model)
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
    sft_support: bool = Field(default=False, description='是否支持微调训练')
