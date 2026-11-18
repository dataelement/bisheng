"""Writer locks and crash-safe inventory for asynchronous knowledge output.

Locks are database transactions, never expiring Redis leases. Gate rows survive
space deletion so an old worker cannot acquire a different lock after cutover.
"""

from sqlalchemy import Column, Index
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import LargeText


class KnowledgeProcessingFence(SQLModelSerializable, table=True):
    __tablename__ = "knowledge_processing_fence"
    id: str = Field(primary_key=True, max_length=100)
    tenant_id: int = Field(index=True)
    space_id: int
    file_id: int  # zero is the space-wide index/rebuild writer


class KnowledgeProcessingArtifact(SQLModelSerializable, table=True):
    __tablename__ = "knowledge_processing_artifact"
    __table_args__ = (Index("ix_kproc_artifact_scope", "tenant_id", "space_id", "file_id"),)
    id: str = Field(primary_key=True, max_length=64)
    tenant_id: int
    space_id: int
    file_id: int
    object_name: str = Field(sa_column=Column(LargeText, nullable=False))
