"""Durable inventory of vector collections superseded by an owned model change."""

from datetime import UTC, datetime

from sqlalchemy import Index
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable


class KnowledgeVectorCleanup(SQLModelSerializable, table=True):
    __tablename__ = "knowledge_vector_cleanup"
    __table_args__ = (Index("ix_kvector_cleanup_due", "tenant_id", "state", "id"),)
    id: str = Field(primary_key=True, max_length=64)
    tenant_id: int = Field(index=True)
    space_id: int = Field(index=True)
    collection_name: str = Field(max_length=255)
    state: str = Field(default="pending", max_length=24)
    attempts: int = Field(default=0)
    error_type: str | None = Field(default=None, max_length=128)
    create_time: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))
