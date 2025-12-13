from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, Text, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable


class RecallBase(SQLModelSerializable):
    message_id: Optional[int] = Field(default=None, index=True, unique=False)
    chat_id: str = Field(index=False)
    keywords: str = Field(sa_column=Column(Text))
    chunk: Optional[str] = Field(default=None, sa_column=Column(Text))
    meta_data: Optional[str] = Field(default=None, sa_column=Column(Text))
    file_id: Optional[int] = Field(default=None, index=False)
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))


class RecallChunk(RecallBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)


class RecallChunkRead(RecallBase):
    id: Optional[int] = None
    score: Optional[int] = None


class RecallChunkQuery(SQLModelSerializable):
    id: Optional[int] = None
    server: Optional[str] = None


class RecallChunkCreate(RecallBase):
    pass
