from datetime import datetime
from typing import Optional

from bisheng.database.models.base import SQLModelSerializable
from sqlalchemy import Column, DateTime, text
from sqlmodel import Field


class KnowledgeBase(SQLModelSerializable):
    user_id: Optional[int] = Field(index=True)
    name: str = Field(index=True)
    description: Optional[str] = Field(index=True)
    model: Optional[str] = Field(index=False)
    collection_name: Optional[str] = Field(index=False)
    index_name: Optional[str] = Field(index=False)
    create_time: Optional[datetime] = Field(
        sa_column=Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=True,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')))


class Knowledge(KnowledgeBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)


class KnowledgeRead(KnowledgeBase):
    id: int
    user_name: Optional[str]


class KnowledgeUpdate(KnowledgeBase):
    id: int
    name: str


class KnowledgeCreate(KnowledgeBase):
    is_partition: bool = True
