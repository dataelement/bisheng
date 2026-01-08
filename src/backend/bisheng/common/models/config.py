from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Column, DateTime, text, Text
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
    WORKSTATION = 'workstation'  # Workbench default model configuration
    LINSIGHT_LLM = 'linsight_llm'  # Ideas Default Model Configuration


class ConfigBase(SQLModelSerializable):
    key: str = Field(index=True, unique=True)
    value: str = Field(sa_column=Column(Text))
    comment: Optional[str] = Field(default=None, index=False)
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP'), onupdate=text('CURRENT_TIMESTAMP')))


class Config(ConfigBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)


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
