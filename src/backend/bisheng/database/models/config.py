from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Column, DateTime, text, Text
from sqlmodel import Field, select

from bisheng.database.models.base import SQLModelSerializable
from bisheng.database.base import session_getter


class ConfigKeyEnum(Enum):
    INIT_DB = 'initdb_config'  # 默认系统配置
    HOME_TAGS = 'home_tags'  # 首页标签ID列表
    WEB_CONFIG = 'web_config'  # 前端自定义的配置项
    KNOWLEDGE_LLM = 'knowledge_llm'  # 知识库默认模型配置
    ASSISTANT_LLM = 'assistant_llm'  # 助手默认模型配置
    EVALUATION_LLM = 'evaluation_llm'  # 评测默认模型配置


class ConfigBase(SQLModelSerializable):
    key: str = Field(index=True, unique=True)
    value: str = Field(sa_column=Column(Text))
    comment: Optional[str] = Field(index=False)
    create_time: Optional[datetime] = Field(sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=False,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')))


class Config(ConfigBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)


class ConfigRead(ConfigBase):
    id: int


class ConfigCreate(ConfigBase):
    pass


class ConfigUpdate(SQLModelSerializable):
    key: str
    value: Optional[str]
    comment: Optional[str]


class ConfigDao(ConfigBase):

    @classmethod
    def get_config(cls, key: ConfigKeyEnum) -> Optional[Config]:
        with session_getter() as session:
            statement = select(Config).where(Config.key == key.value)
            return session.exec(statement).first()

    @classmethod
    def insert_config(cls, config: Config) -> Config:
        with session_getter() as session:
            session.add(config)
            session.commit()
            session.refresh(config)
            return config
