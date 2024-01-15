from datetime import datetime
from typing import Optional

from bisheng.database.models.base import SQLModelSerializable
from sqlalchemy import Column, DateTime, String, text
from sqlmodel import Field


class KnowledgeFileBase(SQLModelSerializable):
    user_id: Optional[int] = Field(index=True)
    knowledge_id: int = Field(index=True)
    file_name: str = Field(index=True)
    md5: Optional[str] = Field(index=False)
    status: Optional[int] = Field(index=False)
    object_name: Optional[str] = Field(index=False)
    remark: Optional[str] = Field(sa_column=String(length=512))
    create_time: Optional[datetime] = Field(
        sa_column=Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=False,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')))


class KnowledgeFile(KnowledgeFileBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)


class KnowledgeFileRead(KnowledgeFileBase):
    id: int


class KnowledgeFileCreate(KnowledgeFileBase):
    pass
