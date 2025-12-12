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
        """ 获取所有的服务提供方 """
        statement = select(LLMServer).order_by(col(LLMServer.update_time).desc())
        with get_sync_db_session() as session:
            return session.exec(statement).all()

    @classmethod
    async def aget_all_server(cls) -> List[LLMServer]:
        """ 异步获取所有的服务提供方 """
        statement = select(LLMServer).order_by(col(LLMServer.update_time).desc())
        async with get_async_db_session() as session:
            result = await session.execute(statement)
            return result.scalars().all()

    @classmethod
    def insert_server_with_models(cls, server: LLMServer, models: List[LLMModel]):
        """ 插入服务提供方和模型 """
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
        """ 异步插入服务提供方和模型 """
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
        """ 更新服务提供方和模型 """
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
            # 添加新增的模型
            session.add_all(add_models)
            # 更新已有模型的数据
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
        """ 获取所有的模型 """
        statement = select(LLMModel)
        with get_sync_db_session() as session:
            return session.exec(statement).all()

    @classmethod
    def get_server_by_id(cls, server_id: int) -> Optional[LLMServer]:
        """ 根据服务ID获取服务提供方 """
        statement = select(LLMServer).where(LLMServer.id == server_id)
        with get_sync_db_session() as session:
            return session.exec(statement).first()

    @classmethod
    async def aget_server_by_id(cls, server_id: int) -> Optional[LLMServer]:
        """ 根据服务ID获取服务提供方 """
        statement = select(LLMServer).where(LLMServer.id == server_id)
        async with get_async_db_session() as session:
            result = await session.execute(statement)
            return result.scalars().first()

    @classmethod
    def get_server_by_ids(cls, server_ids: List[int]) -> List[LLMServer]:
        """ 根据服务ID获取服务提供方 """
        statement = select(LLMServer).where(col(LLMServer.id).in_(server_ids))
        with get_sync_db_session() as session:
            return session.exec(statement).all()

    @classmethod
    async def aget_server_by_ids(cls, server_ids: List[int]) -> List[LLMServer]:
        """ 根据服务ID获取服务提供方 """
        statement = select(LLMServer).where(col(LLMServer.id).in_(server_ids))
        async with get_async_db_session() as session:
            result = await session.execute(statement)
            return result.scalars().all()

    @classmethod
    def get_server_by_name(cls, server_name: str) -> Optional[LLMServer]:
        """ 根据服务名称获取服务提供方 """
        statement = select(LLMServer).where(LLMServer.name == server_name)
        with get_sync_db_session() as session:
            return session.exec(statement).first()

    @classmethod
    async def aget_server_by_name(cls, server_name: str) -> Optional[LLMServer]:
        """ 根据服务名称获取服务提供方 """
        statement = select(LLMServer).where(LLMServer.name == server_name)
        async with get_async_db_session() as session:
            result = await session.execute(statement)
            return result.scalars().first()

    @classmethod
    def get_model_by_id(cls, model_id: int) -> Optional[LLMModel]:
        """ 根据模型ID获取模型 """
        statement = select(LLMModel).where(LLMModel.id == model_id)
        with get_sync_db_session() as session:
            return session.exec(statement).first()

    @classmethod
    async def aget_model_by_id(cls, model_id: int) -> Optional[LLMModel]:
        """ 根据模型ID获取模型 """
        statement = select(LLMModel).where(LLMModel.id == model_id)
        async with get_async_db_session() as session:
            result = await session.execute(statement)
            return result.scalars().first()

    @classmethod
    def get_model_by_ids(cls, model_ids: List[int]) -> List[LLMModel]:
        """ 根据模型ID获取模型 """
        statement = select(LLMModel).where(col(LLMModel.id).in_(model_ids))
        with get_sync_db_session() as session:
            return session.exec(statement).all()

    @classmethod
    async def aget_model_by_ids(cls, model_ids: List[int]) -> List[LLMModel]:
        """ 根据模型ID获取模型 """
        statement = select(LLMModel).where(col(LLMModel.id).in_(model_ids))
        async with get_async_db_session() as session:
            result = await session.execute(statement)
            return result.scalars().all()

    @classmethod
    def get_model_by_type(cls, model_type: LLMModelType) -> Optional[LLMModel]:
        """ 根据模型类型获取第一个创建的模型 """
        statement = select(LLMModel).where(LLMModel.model_type == model_type.value).order_by(
            col(LLMModel.id).asc())
        with get_sync_db_session() as session:
            return session.exec(statement).first()

    @classmethod
    async def aget_model_by_type(cls, model_type: LLMModelType) -> Optional[LLMModel]:
        """ 根据模型类型获取第一个创建的模型 """
        statement = select(LLMModel).where(LLMModel.model_type == model_type.value).order_by(
            col(LLMModel.id).asc())
        async with get_async_db_session() as session:
            result = await session.execute(statement)
            return result.scalars().first()

    @classmethod
    def get_model_by_server_ids(cls, server_ids: List[int]) -> List[LLMModel]:
        """ 根据服务ID获取模型 """
        statement = select(LLMModel).where(col(LLMModel.server_id).in_(server_ids)).order_by(
            col(LLMModel.update_time).desc())
        with get_sync_db_session() as session:
            return session.exec(statement).all()

    @classmethod
    async def aget_model_by_server_ids(cls, server_ids: List[int]) -> List[LLMModel]:
        """ 根据服务ID获取第一个创建的模型 """
        statement = select(LLMModel).where(col(LLMModel.server_id).in_(server_ids)).order_by(
            col(LLMModel.update_time).desc())
        async with get_async_db_session() as session:
            result = await session.execute(statement)
            return result.scalars().all()

    @classmethod
    def update_model_status(cls, model_id: int, status: int, remark: str = ''):
        """ 更新模型状态 """
        with get_sync_db_session() as session:
            session.exec(
                update(LLMModel).where(col(LLMModel.id) == model_id).values(status=status,
                                                                            remark=remark))
            session.commit()

    @classmethod
    async def aupdate_model_status(cls, model_id: int, status: int, remark: str = ''):
        """ 异步更新模型状态 """
        async with get_async_db_session() as session:
            await session.execute(
                update(LLMModel).where(col(LLMModel.id) == model_id).values(status=status,
                                                                            remark=remark))
            await session.commit()

    @classmethod
    def update_model_online(cls, model_id: int, online: bool):
        """ 更新模型在线状态 """
        with get_sync_db_session() as session:
            session.exec(update(LLMModel).where(col(LLMModel.id) == model_id).values(online=online))
            session.commit()

    @classmethod
    async def aupdate_model_online(cls, model_id: int, online: bool):
        """ 异步更新模型在线状态 """
        async with get_async_db_session() as session:
            await session.execute(update(LLMModel).where(col(LLMModel.id) == model_id).values(online=online))
            await session.commit()

    @classmethod
    def delete_server_by_id(cls, server_id: int):
        """ 根据服务ID删除服务提供方 """
        with get_sync_db_session() as session:
            session.exec(delete(LLMServer).where(col(LLMServer.id) == server_id))
            session.exec(delete(LLMModel).where(col(LLMModel.server_id) == server_id))
            session.commit()

    @classmethod
    async def adelete_server_by_id(cls, server_id: int):
        """ 根据服务ID删除服务提供方 """
        async with get_async_db_session() as session:
            await session.execute(delete(LLMServer).where(col(LLMServer.id) == server_id))
            await session.execute(delete(LLMModel).where(col(LLMModel.server_id) == server_id))
            await session.commit()

    @classmethod
    def delete_model_by_ids(cls, model_ids: List[int]):
        """ 根据模型ID删除模型 """
        with get_sync_db_session() as session:
            session.exec(delete(LLMModel).where(col(LLMModel.id).in_(model_ids)))
            session.commit()

    @classmethod
    async def adelete_model_by_ids(cls, model_ids: List[int]):
        """ 根据模型ID删除模型 """
        async with get_async_db_session() as session:
            await session.execute(delete(LLMModel).where(col(LLMModel.id).in_(model_ids)))
            await session.commit()
