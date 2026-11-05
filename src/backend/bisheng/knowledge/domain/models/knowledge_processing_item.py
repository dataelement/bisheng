"""One recoverable file/version item in an F118 processing task."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Column, Index, UniqueConstraint
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import JsonType, LargeText


def processing_item_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class KnowledgeProcessingItem(SQLModelSerializable, table=True):
    __tablename__ = "knowledge_processing_item"
    __table_args__ = (
        UniqueConstraint("job_id", "file_id", "version_id", name="uk_kproc_item_version"),
        Index("ix_kproc_item_job_state", "tenant_id", "job_id", "state", "id"),
        Index("ix_kproc_item_lease", "state", "lease_until", "id"),
    )

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True, max_length=36)
    tenant_id: int = Field(index=True)
    job_id: str = Field(max_length=36, index=True)
    file_id: int = Field(index=True)
    document_id: int
    version_id: int
    expected_space_id: int
    expected_parent_id: int | None = Field(default=None)

    # Actual resolved parsing options, not a task-to-model binding.
    processing_snapshot: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    state: str = Field(default="pending", max_length=24)
    step: str = Field(default="pending", max_length=64)
    checkpoint: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    result: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    attempt: int = Field(default=0)
    claim_generation: int = Field(default=0)
    lease_token: str | None = Field(default=None, max_length=36)
    lease_until: datetime | None = Field(default=None)
    error_code: int | None = Field(default=None)
    error_message: str | None = Field(default=None, sa_column=Column(LargeText, nullable=True))

    started_at: datetime | None = Field(default=None)
    finished_at: datetime | None = Field(default=None)
    create_time: datetime = Field(default_factory=processing_item_now)
    update_time: datetime = Field(default_factory=processing_item_now)
