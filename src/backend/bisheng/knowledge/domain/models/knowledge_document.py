"""Logical document — anchors a version chain in a knowledge space."""
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT


class KnowledgeDocumentBase(SQLModelSerializable):
    knowledge_id: int = Field(index=True, description="Owning knowledge space ID")
    file_level_path: Optional[str] = Field(
        default=None,
        index=True,
        description="Parent folder path, e.g. '/12/34'. None = root.",
    )
    level: Optional[int] = Field(default=0, description="Folder depth")
    primary_version_id: Optional[int] = Field(
        default=None,
        description="FK to knowledge_document_version.id of the current primary version",
    )
    create_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')
        ),
    )
    update_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT
        ),
    )


class KnowledgeDocument(KnowledgeDocumentBase, table=True):
    __tablename__ = 'knowledge_document'
    id: Optional[int] = Field(default=None, primary_key=True)


class KnowledgeDocumentRead(KnowledgeDocumentBase):
    id: int


class KnowledgeDocumentCreate(KnowledgeDocumentBase):
    pass
