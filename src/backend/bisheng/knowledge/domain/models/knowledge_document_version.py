"""Document version — one row per physical file version inside a logical document."""
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, UniqueConstraint, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT


class KnowledgeDocumentVersionBase(SQLModelSerializable):
    document_id: int = Field(index=True, description="FK to knowledge_document.id")
    knowledge_file_id: int = Field(
        index=True, description="FK to knowledgefile.id (the physical file)"
    )
    version_no: int = Field(description="Version number within the document (V1=1, V2=2, ...)")
    is_primary: bool = Field(
        default=False, description="Whether this version is the document's current primary version"
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


class KnowledgeDocumentVersion(KnowledgeDocumentVersionBase, table=True):
    __tablename__ = 'knowledge_document_version'
    __table_args__ = (
        UniqueConstraint('document_id', 'version_no', name='uk_kdv_document_version'),
    )
    id: Optional[int] = Field(default=None, primary_key=True)


class KnowledgeDocumentVersionRead(KnowledgeDocumentVersionBase):
    id: int


class KnowledgeDocumentVersionCreate(KnowledgeDocumentVersionBase):
    pass
