"""One durable idempotency receipt per explicit processing retry request."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import CheckConstraint, Column, Index, Integer, UniqueConstraint, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import JsonType


def retry_receipt_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class KnowledgeProcessingRetryReceipt(SQLModelSerializable, table=True):
    __tablename__ = "knowledge_processing_retry_receipt"
    __table_args__ = (
        UniqueConstraint("tenant_id", "job_id", "idempotency_key", name="uq_kpr_job_key"),
        Index("ix_kpr_job_revision", "tenant_id", "job_id", "accepted_job_revision", "id"),
        CheckConstraint("tenant_id > 0 AND actor_user_id > 0", name="ck_kpr_identity"),
        CheckConstraint(
            "expected_job_revision >= 0 AND accepted_job_revision > expected_job_revision AND item_count > 0",
            name="ck_kpr_revision",
        ),
    )

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True, max_length=36)
    tenant_id: int | None = Field(
        default=None, sa_column=Column(Integer, nullable=False, server_default=text("1"), index=True)
    )
    job_id: str = Field(max_length=36)
    idempotency_key: str = Field(max_length=64)
    request_hash: str = Field(max_length=64)
    actor_user_id: int
    # Explicit retry provenance, not a new authorization source. Services must
    # revalidate the current credential and frozen target bounds before work.
    actor_reference: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    expected_job_revision: int
    accepted_job_revision: int
    item_count: int
    accepted_at: datetime = Field(default_factory=retry_receipt_now)
    create_time: datetime = Field(default_factory=retry_receipt_now)
    update_time: datetime = Field(default_factory=retry_receipt_now)
