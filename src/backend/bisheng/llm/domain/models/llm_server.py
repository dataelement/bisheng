from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy import CHAR, JSON, Column, DateTime, Text, UniqueConstraint, delete, text, update
from sqlmodel import Field, select, col

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_sync_db_session, get_async_db_session
from bisheng.llm.domain.const import LLMModelType


class LLMServerBase(SQLModelSerializable):
    name: str = Field(default='', index=True, unique=True, description='Service name')
    description: Optional[str] = Field(default='', sa_column=Column(Text), description='Service Description')
    type: str = Field(sa_column=Column(CHAR(20)), description='Service Provider Type')
    limit_flag: bool = Field(default=False, description='Whether to turn on the daily call limit')
    limit: int = Field(default=0, description='Daily call limit')
    config: Optional[Dict] = Field(default=None, sa_column=Column(JSON), description='Service Provider Public Configuration')
    user_id: int = Field(default=0, description='creatorID')
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))


class LLMModelBase(SQLModelSerializable):
    server_id: Optional[int] = Field(default=None, nullable=False, index=True, description='SERVICESID')
    name: str = Field(default='', description='Model Display Name')
    description: Optional[str] = Field(default='', sa_column=Column(Text), description='Model Description')
    model_name: str = Field(default='', description='Model name, parameters used when instantiating components')
    model_type: str = Field(sa_column=Column(CHAR(20)), description='model type')
    config: Optional[Dict] = Field(default=None, sa_column=Column(JSON), description='Service Provider Public Configuration')
    status: int = Field(default=2, description='Model status.0Normal1abnormal:, 2: Unknown')
    remark: Optional[str] = Field(default='', sa_column=Column(Text), description='Abnormal reason')
    online: bool = Field(default=True, description='Online')
    user_id: int = Field(default=0, description='creatorID')
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))


class LLMServer(LLMServerBase, table=True):
    __tablename__ = 'llm_server'

    id: Optional[int] = Field(default=None, nullable=False, primary_key=True, description='Service UniqueID')


class LLMModel(LLMModelBase, table=True):
    __tablename__ = 'llm_model'
    __table_args__ = (UniqueConstraint('server_id', 'model_name', name='server_model_uniq'),)

    id: Optional[int] = Field(default=None, nullable=False, primary_key=True, description='Model UniqueID')


class LLMDao:

    @classmethod
    def get_all_server(cls) -> List[LLMServer]:
        """ Get all service providers """
        statement = select(LLMServer).order_by(col(LLMServer.update_time).desc())
        with get_sync_db_session() as session:
            return session.exec(statement).all()

    @classmethod
    async def aget_all_server(cls) -> List[LLMServer]:
        """ Get all providers asynchronously """
        statement = select(LLMServer).order_by(col(LLMServer.update_time).desc())
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    def insert_server_with_models(cls, server: LLMServer, models: List[LLMModel]):
        """ Insert Service Provider and Model """
        with get_sync_db_session() as session:
            session.add(server)
            session.flush()
            for model in models:
                model.server_id = server.id
            session.add_all(models)
            session.commit()
            session.refresh(server)
            return server

    @classmethod
    async def ainsert_server_with_models(cls, server: LLMServer, models: List[LLMModel]):
        """ Insert service providers and models asynchronously """
        async with get_async_db_session() as session:
            session.add(server)
            await session.flush()
            for model in models:
                model.server_id = server.id
            session.add_all(models)
            await session.commit()
            await session.refresh(server)
            return server

    @classmethod
    async def update_server_with_models(cls, server: LLMServer, models: List[LLMModel]):
        """ Update Service Providers and Models """
        async with get_async_db_session() as session:
            session.add(server)

            add_models = []
            update_models = []
            for model in models:
                if model.id:
                    update_models.append(model)
                else:
                    add_models.append(model)
            # Delete model
            await session.exec(
                delete(LLMModel).where(col(LLMModel.server_id) == server.id,
                                       col(LLMModel.id).not_in([model.id for model in update_models])))
            # Add New Model
            session.add_all(add_models)
            # Update data for existing models
            for one in update_models:
                await session.exec(
                    update(LLMModel).where(LLMModel.id == one.id).values(
                        name=one.name,
                        description=one.description,
                        model_name=one.model_name,
                        model_type=one.model_type,
                        config=one.config))

            await session.commit()
            await session.refresh(server)
            return server

    @classmethod
    def get_all_model(cls) -> List[LLMModel]:
        """ Get all models """
        statement = select(LLMModel)
        with get_sync_db_session() as session:
            return session.exec(statement).all()

    @classmethod
    def get_server_by_id(cls, server_id: int) -> Optional[LLMServer]:
        """ According to serviceIDGet Service Providers """
        statement = select(LLMServer).where(LLMServer.id == server_id)
        with get_sync_db_session() as session:
            return session.exec(statement).first()

    @classmethod
    async def aget_server_by_id(cls, server_id: int) -> Optional[LLMServer]:
        """ According to serviceIDGet Service Providers """
        statement = select(LLMServer).where(LLMServer.id == server_id)
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.first()

    @classmethod
    def get_server_by_ids(cls, server_ids: List[int]) -> List[LLMServer]:
        """ According to serviceIDGet Service Providers """
        statement = select(LLMServer).where(col(LLMServer.id).in_(server_ids))
        with get_sync_db_session() as session:
            return session.exec(statement).all()

    @classmethod
    async def aget_server_by_ids(cls, server_ids: List[int]) -> List[LLMServer]:
        """ According to serviceIDGet Service Providers """
        statement = select(LLMServer).where(col(LLMServer.id).in_(server_ids))
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    def get_server_by_name(cls, server_name: str) -> Optional[LLMServer]:
        """ Get Service Provider by Service Name """
        statement = select(LLMServer).where(LLMServer.name == server_name)
        with get_sync_db_session() as session:
            return session.exec(statement).first()

    @classmethod
    async def aget_server_by_name(cls, server_name: str) -> Optional[LLMServer]:
        """ Get Service Provider by Service Name """
        statement = select(LLMServer).where(LLMServer.name == server_name)
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.first()

    @classmethod
    def get_model_by_id(cls, model_id: int) -> Optional[LLMModel]:
        """ According to the modelIDGrabbed Objects """
        statement = select(LLMModel).where(LLMModel.id == model_id)
        with get_sync_db_session() as session:
            return session.exec(statement).first()

    @classmethod
    async def aget_model_by_id(cls, model_id: int) -> Optional[LLMModel]:
        """ According to the modelIDGrabbed Objects """
        statement = select(LLMModel).where(LLMModel.id == model_id)
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.first()

    @classmethod
    def get_model_by_ids(cls, model_ids: List[int]) -> List[LLMModel]:
        """ According to the modelIDGrabbed Objects """
        statement = select(LLMModel).where(col(LLMModel.id).in_(model_ids))
        with get_sync_db_session() as session:
            return session.exec(statement).all()

    @classmethod
    async def aget_model_by_ids(cls, model_ids: List[int]) -> List[LLMModel]:
        """ According to the modelIDGrabbed Objects """
        statement = select(LLMModel).where(col(LLMModel.id).in_(model_ids))
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    def get_model_by_type(cls, model_type: LLMModelType) -> Optional[LLMModel]:
        """ Get first created model based on model type """
        statement = select(LLMModel).where(LLMModel.model_type == model_type.value).order_by(
            col(LLMModel.id).asc())
        with get_sync_db_session() as session:
            return session.exec(statement).first()

    @classmethod
    async def aget_model_by_type(cls, model_type: LLMModelType) -> Optional[LLMModel]:
        """ Get first created model based on model type """
        statement = select(LLMModel).where(LLMModel.model_type == model_type.value).order_by(
            col(LLMModel.id).asc())
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.first()

    @classmethod
    def get_model_by_server_ids(cls, server_ids: List[int]) -> List[LLMModel]:
        """ According to serviceIDGrabbed Objects """
        statement = select(LLMModel).where(col(LLMModel.server_id).in_(server_ids)).order_by(
            col(LLMModel.update_time).desc())
        with get_sync_db_session() as session:
            return session.exec(statement).all()

    @classmethod
    async def aget_model_by_server_ids(cls, server_ids: List[int]) -> List[LLMModel]:
        """ According to serviceIDGet the first model created """
        statement = select(LLMModel).where(col(LLMModel.server_id).in_(server_ids)).order_by(
            col(LLMModel.update_time).desc())
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    def update_model_status(cls, model_id: int, status: int, remark: str = ''):
        """ Update model status """
        with get_sync_db_session() as session:
            session.exec(
                update(LLMModel).where(col(LLMModel.id) == model_id).values(status=status,
                                                                            remark=remark))
            session.commit()

    @classmethod
    async def aupdate_model_status(cls, model_id: int, status: int, remark: str = ''):
        """ Asynchronously update model status """
        async with get_async_db_session() as session:
            await session.exec(
                update(LLMModel).where(col(LLMModel.id) == model_id).values(status=status,
                                                                            remark=remark))
            await session.commit()

    @classmethod
    def update_model_online(cls, model_id: int, online: bool):
        """ Update model online status """
        with get_sync_db_session() as session:
            session.exec(update(LLMModel).where(col(LLMModel.id) == model_id).values(online=online))
            session.commit()

    @classmethod
    async def aupdate_model_online(cls, model_id: int, online: bool):
        """ Asynchronous update model online status """
        async with get_async_db_session() as session:
            await session.exec(update(LLMModel).where(col(LLMModel.id) == model_id).values(online=online))
            await session.commit()

    @classmethod
    def delete_server_by_id(cls, server_id: int):
        """ According to serviceIDDelete Service Provider """
        with get_sync_db_session() as session:
            session.exec(delete(LLMServer).where(col(LLMServer.id) == server_id))
            session.exec(delete(LLMModel).where(col(LLMModel.server_id) == server_id))
            session.commit()

    @classmethod
    async def adelete_server_by_id(cls, server_id: int):
        """ According to serviceIDDelete Service Provider """
        async with get_async_db_session() as session:
            await session.exec(delete(LLMServer).where(col(LLMServer.id) == server_id))
            await session.exec(delete(LLMModel).where(col(LLMModel.server_id) == server_id))
            await session.commit()

    @classmethod
    def delete_model_by_ids(cls, model_ids: List[int]):
        """ According to the modelIDDelete model """
        with get_sync_db_session() as session:
            session.exec(delete(LLMModel).where(col(LLMModel.id).in_(model_ids)))
            session.commit()

    @classmethod
    async def adelete_model_by_ids(cls, model_ids: List[int]):
        """ According to the modelIDDelete model """
        async with get_async_db_session() as session:
            await session.exec(delete(LLMModel).where(col(LLMModel.id).in_(model_ids)))
            await session.commit()
