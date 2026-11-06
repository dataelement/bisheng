"""Durable external cleanup intent committed together with formal deletion."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Column, Index, Text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import JsonType

DELETE_STEPS = ("fga", "minio", "es", "milvus")


def deletion_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class KnowledgeSpaceDeleteJob(SQLModelSerializable, table=True):
    __tablename__ = "knowledge_space_delete_job"
    __table_args__ = (Index("ix_space_delete_due", "state", "next_attempt_at", "id"),)

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True, max_length=36)
    tenant_id: int = Field(index=True)
    space_id: int = Field(index=True)
    applicant_user_id: int
    manifest: dict = Field(sa_column=Column(JsonType, nullable=False))
    completed_steps: list[str] = Field(default_factory=list, sa_column=Column(JsonType, nullable=False))
    state: str = Field(default="PENDING", max_length=16)
    attempts: int = Field(default=0)
    lease_token: str | None = Field(default=None, max_length=36)
    lease_until: datetime | None = Field(default=None)
    next_attempt_at: datetime = Field(default_factory=deletion_now)
    last_error: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    create_time: datetime = Field(default_factory=deletion_now)
    update_time: datetime = Field(default_factory=deletion_now)
