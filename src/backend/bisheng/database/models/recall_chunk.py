from datetime import datetime
from typing import Optional

from bisheng.database.models.base import SQLModelSerializable
from sqlalchemy import Column, DateTime, Text, text
from sqlmodel import Field


class RecallBase(SQLModelSerializable):
    message_id: Optional[int] = Field(index=True, unique=False)
    chat_id: str = Field(index=False)
    keywords: str = Field(sa_column=Column(Text))
    chunk: Optional[str] = Field(sa_column=Column(Text))
    meta_data: Optional[str] = Field(sa_column=Column(Text))
    file_id: Optional[int] = Field(index=False)

    create_time: Optional[datetime] = Field(
        sa_column=Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=False,
                         index=True,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')))


class RecallChunk(RecallBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)


class RecallChunkRead(RecallBase):
    id: Optional[int]
    score: Optional[int]


class RecallChunkQuery(SQLModelSerializable):
    id: Optional[int]
    server: Optional[str]


class RecallChunkCreate(RecallBase):
    pass
