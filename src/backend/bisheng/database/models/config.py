from datetime import datetime
from typing import Optional

from bisheng.database.models.base import SQLModelSerializable
from sqlalchemy import Column, DateTime, String, text
from sqlmodel import Field


class ConfigBase(SQLModelSerializable):
    key: str = Field(index=True, unique=True)
    value: str = Field(sa_column=Column(String(length=8096)))
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
