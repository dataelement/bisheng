from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy import CHAR, JSON, Column, DateTime, Text, UniqueConstraint, delete, text, update,VARCHAR
from sqlmodel import Field, select, col

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_sync_db_session, get_async_db_session
from ..const import LLMModelType
from sqlalchemy import Integer
from pydantic import field_validator
from sqlalchemy.types import TypeDecorator, JSON
import json

# 自定义 JSON 类型：自动处理字符串与字典的转换
class DMJSON(TypeDecorator):
    impl = JSON  # 底层依赖达梦的 JSON 类型
    def process_bind_param(self, value, dialect):
        # 写入数据库：字典转 JSON 字符串
        if value is None:
            return None
        return json.dumps(value)
    def process_result_value(self, value, dialect):
        # 读取数据库：JSON 字符串转字典
        if value is None:
            return None
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return {}
        return value
class LLMServerBase(SQLModelSerializable):
    name: str = Field(default='', index=True, unique=True, description='服务名称')
    description: Optional[str] = Field(default='', sa_column=Column(Text), description='服务描述')
    type: str = Field(sa_column=Column(VARCHAR), description='服务提供方类型')
    limit_flag: bool = Field(default=False, description='是否开启每日调用次数限制')
    limit: int = Field(default=0, description='每日调用次数限制')
    config: Optional[Dict] = Field(default=None, sa_column=Column(DMJSON), description='服务提供方公共配置')
    user_id: int = Field(default=0, description='创建人ID')
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))


class LLMModelBase(SQLModelSerializable):
    server_id: Optional[int] = Field(default=None, nullable=False, index=True, description='服务ID')
    name: str = Field(default='', description='模型展示名')
    description: Optional[str] = Field(default='', sa_column=Column(Text), description='模型描述')
    model_name: str = Field(default='', description='模型名称，实例化组件时用的参数')
    model_type: str = Field(sa_column=Column(VARCHAR), description='模型类型')
    config: Optional[Dict] = Field(default=None, sa_column=Column(DMJSON), description='服务提供方公共配置')
    status: int = Field(default=2, description='模型状态。0：正常，1：异常, 2: 未知')
    remark: Optional[str] = Field(default='', sa_column=Column(Text), description='异常原因')
    online: bool = Field(default=True, description='是否在线')
    user_id: int = Field(default=0, description='创建人ID')
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))


class LLMServer(LLMServerBase, table=True):
    __tablename__ = 'llm_server'

    # id: Optional[int] = Field(default=None, nullable=False, primary_key=True, description='服务唯一ID')
    id: Optional[int] = Field(default=None, description='服务唯一ID', sa_column=Column(Integer, primary_key=True, autoincrement=True))


class LLMModel(LLMModelBase, table=True):
    __tablename__ = 'llm_model'
    __table_args__ = (UniqueConstraint('server_id', 'model_name', name='server_model_uniq'),)

    # id: Optional[int] = Field(default=None, nullable=False, primary_key=True, description='模型唯一ID')
    id: Optional[int] = Field(default=None, description='模型唯一ID', sa_column=Column(Integer, primary_key=True, autoincrement=True))


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
            result = await session.execute(statement)
            return result.scalars().all()

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
            # 删除模型
            await session.execute(
                delete(LLMModel).where(col(LLMModel.server_id) == server.id,
                                       col(LLMModel.id).not_in([model.id for model in update_models])))
            # Add New Model
            session.add_all(add_models)
            # Update data for existing models
            for one in update_models:
                await session.execute(
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
    @wrapper_bisheng_llm_info(key_prefix="llm:server:")
    def get_server_by_id(cls, server_id: int, *, cache: bool = False) -> Optional[LLMServer]:
        """ According to serviceIDGet Service Providers """
        statement = select(LLMServer).where(LLMServer.id == server_id)
        with get_sync_db_session() as session:
            return session.exec(statement).first()

    @classmethod
    @wrapper_bisheng_llm_info_async(key_prefix="llm:server:")
    async def aget_server_by_id(cls, server_id: int, *, cache: bool = False) -> Optional[LLMServer]:
        """ According to serviceIDGet Service Providers """
        statement = select(LLMServer).where(LLMServer.id == server_id)
        async with get_async_db_session() as session:
            result = await session.execute(statement)
            return result.scalars().first()

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
            result = await session.execute(statement)
            return result.scalars().all()

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
            result = await session.execute(statement)
            return result.scalars().first()

    @classmethod
    @wrapper_bisheng_llm_info(key_prefix="llm:model:")
    def get_model_by_id(cls, model_id: int, *, cache: bool = False) -> Optional[LLMModel]:
        """ According to the modelIDGrabbed Objects """
        # get from cache
        statement = select(LLMModel).where(LLMModel.id == model_id)
        with get_sync_db_session() as session:
            return session.exec(statement).first()

    @classmethod
    @wrapper_bisheng_llm_info_async(key_prefix="llm:model:")
    async def aget_model_by_id(cls, model_id: int, *, cache: bool = False) -> Optional[LLMModel]:
        """ According to the modelIDGrabbed Objects """
        statement = select(LLMModel).where(LLMModel.id == model_id)
        async with get_async_db_session() as session:
            result = await session.execute(statement)
            return result.scalars().first()

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
            result = await session.execute(statement)
            return result.scalars().all()

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
            result = await session.execute(statement)
            return result.scalars().first()

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
            result = await session.execute(statement)
            return result.scalars().all()

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
            await session.execute(
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
            await session.execute(update(LLMModel).where(col(LLMModel.id) == model_id).values(online=online))
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
            await session.execute(delete(LLMServer).where(col(LLMServer.id) == server_id))
            await session.execute(delete(LLMModel).where(col(LLMModel.server_id) == server_id))
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
            await session.execute(delete(LLMModel).where(col(LLMModel.id).in_(model_ids)))
            await session.commit()
