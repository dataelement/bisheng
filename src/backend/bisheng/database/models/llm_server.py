from datetime import datetime
from enum import Enum
from typing import List, Tuple, Optional, Dict
from uuid import UUID, uuid4

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable
from bisheng.database.models.role_access import AccessType, RoleAccess
from sqlalchemy import JSON, Column, DateTime, Text, and_, func, or_, text, UniqueConstraint
from sqlmodel import Field, select


# 服务提供方枚举
class LLMServerType(Enum):
    OPENAI = 'openai'
    AZURE_OPENAI = 'azure_openai'
    OLLAMA = 'ollama'
    XINFERENCE = 'xinference'
    LLAMACPP = 'llamacpp'
    VLLM = 'vllm'
    QWEN = 'qwen'  # 阿里通义千问
    QIAN_FAN = 'qianfan'  # 百度千帆
    CHAT_GLM = 'chat_glm'  # 智谱清言
    MINIMAX = 'minimax'
    ANTHROPIC = 'anthropic'


# 模型类型枚举
class LLMModelType(Enum):
    LLM = 'llm'
    EMBEDDING = 'embedding'
    RERANK = 'rerank'


class LLMServerBase(SQLModelSerializable):
    name: str = Field(default='', index=True, unique=True, description='服务名称')
    desc: str = Field(default='', sa_column=Column(Text), description='服务描述')
    type: LLMServerType = Field(description='服务提供方类型')
    limit_flag: bool = Field(default=False, description='是否开启每日调用次数限制')
    limit: int = Field(default=0, description='每日调用次数限制')
    config: Optional[Dict] = Field(sa_column=Column(JSON), description='服务提供方公共配置')
    user_id: int = Field(default='', description='创建人ID')
    create_time: Optional[datetime] = Field(sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=False,
                         server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))


class LLMModelBase(SQLModelSerializable):
    server_id: int = Field(nullable=False, index=True, description='服务ID')
    name: str = Field(default='', description='模型展示名')
    model_name: str = Field(default='', description='模型名称，实例化组件时用的参数')
    model_type: LLMModelType = Field(description='模型类型')
    config: Optional[Dict] = Field(sa_column=Column(JSON), description='服务提供方公共配置')
    desc: str = Field(default='', sa_column=Column(Text), description='模型描述')
    status: int = Field(default=0, description='模型状态')
    online: bool = Field(default=False, description='是否在线')
    user_id: int = Field(default='', description='创建人ID')
    create_time: Optional[datetime] = Field(sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=False,
                         server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))


class LLMServer(LLMServerBase, table=True):
    __tablename__ = 'llm_server'

    id: Optional[int] = Field(nullable=False, primary_key=True, description='服务唯一ID')


class LLMModel(LLMModelBase, table=True):
    __tablename__ = 'llm_model'
    # __table_args__ = (UniqueConstraint('server_id', 'model_name', name='server_model_uniq'),)

    id: Optional[int] = Field(nullable=False, primary_key=True, description='模型唯一ID')


class LLMDao:

    @classmethod
    def get_all_server(cls) -> List[LLMServer]:
        """ 获取所有的服务提供方 """
        statement = select(LLMServer).order_by(LLMServer.update_time.desc())
        with session_getter() as session:
            return session.exec(statement).all()

    @classmethod
    def insert_server_with_models(cls, server: LLMServer, models: List[LLMModel]):
        """ 插入服务提供方和模型 """
        with session_getter() as session:
            session.add(server)
            session.flush()
            for model in models:
                model.server_id = server.id
            session.add_all(models)
            session.commit()
            return server

    @classmethod
    def get_all_model(cls) -> List[LLMModel]:
        """ 获取所有的模型 """
        statement = select(LLMModel)
        with session_getter() as session:
            return session.exec(statement).all()

    @classmethod
    def get_server_by_id(cls, server_id: int) -> Optional[LLMServer]:
        """ 根据服务ID获取服务提供方 """
        statement = select(LLMServer).where(LLMServer.id == server_id)
        with session_getter() as session:
            return session.exec(statement).first()

    @classmethod
    def get_model_by_id(cls, model_id: int) -> Optional[LLMModel]:
        """ 根据模型ID获取模型 """
        statement = select(LLMModel).where(LLMModel.id == model_id)
        with session_getter() as session:
            return session.exec(statement).first()

    @classmethod
    def get_model_by_server_ids(cls, server_ids: List[int]) -> List[LLMModel]:
        """ 根据服务ID获取模型 """
        statement = select(LLMModel).where(LLMModel.server_id.in_(server_ids)).order_by(LLMModel.update_time.desc())
        with session_getter() as session:
            return session.exec(statement).all()
