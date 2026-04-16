from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Column, DateTime, text
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlmodel import Field, select

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_sync_db_session, get_async_db_session


class ConfigKeyEnum(Enum):
    INIT_DB = 'initdb_config'  # Default System Configuration
    HOME_TAGS = 'home_tags'  # Home LabelIDVertical
    WEB_CONFIG = 'web_config'  # Configuration items for front-end customization
    KNOWLEDGE_LLM = 'knowledge_llm'  # Knowledge Base Default Model Configuration
    ASSISTANT_LLM = 'assistant_llm'  # Assistant Default Model Configuration
    EVALUATION_LLM = 'evaluation_llm'  # Review default model configuration
    WORKFLOW_LLM = 'workflow_llm'  # Workflow default model configuration
    WORKSTATION = 'workstation'  # Daily Chat configuration
    WORKSTATION_LINSIGHT = 'workstation_linsight'  # Linsight configuration
    WORKSTATION_SUBSCRIPTION = 'workstation_subscription'  # Subscription configuration
    WORKSTATION_KNOWLEDGE_SPACE = 'workstation_knowledge_space'  # Knowledge Space Configuration

    LINSIGHT_LLM = 'linsight_llm'  # workstation Default Model Configuration


class ConfigBase(SQLModelSerializable):
    key: str = Field(index=True, unique=True)
    value: str = Field(sa_column=Column(LONGTEXT))
    comment: Optional[str] = Field(default=None, index=False)
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP'), onupdate=text('CURRENT_TIMESTAMP')))


class Config(ConfigBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    __table_args__ = {
        "mysql_charset": "utf8mb4",
        "mysql_collate": "utf8mb4_unicode_ci"
    }


class ConfigRead(ConfigBase):
    id: int


class ConfigCreate(ConfigBase):
    pass


class ConfigUpdate(SQLModelSerializable):
    key: str
    value: Optional[str] = None
    comment: Optional[str] = None


class ConfigDao(ConfigBase):

    @classmethod
    def get_config(cls, key: ConfigKeyEnum) -> Optional[Config]:
        with get_sync_db_session() as session:
            statement = select(Config).where(Config.key == key.value)
            config = session.exec(statement).first()
            return config

    @classmethod
    async def aget_config(cls, key: ConfigKeyEnum) -> Optional[Config]:
        async with get_async_db_session() as session:
            statement = select(Config).where(Config.key == key.value)
            config = await session.exec(statement)
            config = config.first()
            return config

    @classmethod
    async def aget_config_by_key(cls, key: str) -> Optional[Config]:
        """按任意字符串 key 读取配置（用于非 ConfigKeyEnum 的扩展项）。"""
        async with get_async_db_session() as session:
            statement = select(Config).where(Config.key == key)
            result = await session.exec(statement)
            return result.first()

    @classmethod
    def insert_config(cls, config: Config) -> Config:
        with get_sync_db_session() as session:
            session.add(config)
            session.commit()
            session.refresh(config)
            return config

    @classmethod
    async def async_insert_config(cls, config: Config) -> Config:
        async with get_async_db_session() as session:
            session.add(config)
            await session.commit()
            await session.refresh(config)
            return config

    @classmethod
    async def insert_or_update_config(cls, key: str, value: str) -> Config:
        async with get_async_db_session() as session:
            statement = select(Config).where(Config.key == key)
            config = await session.exec(statement)
            config = config.first()
            if config:
                config.value = value
                session.add(config)
                await session.commit()
                await session.refresh(config)
                return config
            else:
                new_config = Config(key=key, value=value)
                session.add(new_config)
                await session.commit()
                await session.refresh(new_config)
                return new_config
