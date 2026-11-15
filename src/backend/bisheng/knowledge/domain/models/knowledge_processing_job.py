"""Durable F118 business task and dispatch intent, independent of Celery results."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import BigInteger, Column, Index, String, UniqueConstraint
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import JsonType, LargeText


def processing_now() -> datetime:
    """Persist naive UTC consistently with existing task ledgers."""
    return datetime.now(UTC).replace(tzinfo=None)


class KnowledgeProcessingJob(SQLModelSerializable, table=True):
    __tablename__ = "knowledge_processing_job"
    __table_args__ = (
        UniqueConstraint("tenant_id", "kind", "idempotency_key", name="uk_kproc_job_request"),
        Index("ix_kproc_job_space_state", "tenant_id", "space_id", "state", "id"),
        Index("ix_kproc_job_dispatch", "pending_dispatch", "next_dispatch_at", "id"),
        Index("ix_kproc_job_lease", "state", "lease_until", "id"),
    )

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True, max_length=36)
    tenant_id: int = Field(index=True)
    space_id: int = Field(index=True)
    kind: str = Field(max_length=32)
    state: str = Field(default="accepted", max_length=24)
    actor_user_id: int
    # Optional move provenance only; never infer these facts from the audit user.
    actor_subject_type: str | None = Field(default=None, exclude=True, sa_column=Column(String(32), nullable=True))
    actor_subject_id: int | None = Field(default=None, exclude=True, sa_column=Column(BigInteger, nullable=True))
    # Identifiers and original narrowing metadata only; not an authorization
    # source. Execution revalidates the credential and retains its narrowing.
    actor_reference: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    idempotency_key: str = Field(max_length=64)
    request_hash: str = Field(max_length=64)
    parameters: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    scope_manifest: list[dict] = Field(default_factory=list, sa_column=Column(JsonType, nullable=False))

    # Private durable facts; only the later receipt-bound ready path may issue them.
    move_logical_marker: dict | None = Field(
        default=None, exclude=True, repr=False, sa_column=Column(JsonType, nullable=True)
    )

    # Only the relevant model/index revision determines obsolescence.
    # space_config_version is provenance for frozen parsing defaults instead.
    expected_model_config_revision: int
    # Immutable acceptance evidence. Older trial rows may lack this fact;
    # never infer it from the expected revision after an operation cutover.
    accepted_model_config_revision: int | None = Field(default=None)
    expected_index_generation: str | None = Field(default=None, max_length=64)
    space_config_version: int = Field(default=0)
    claim_generation: int = Field(default=0)
    lease_token: str | None = Field(default=None, max_length=36)
    lease_until: datetime | None = Field(default=None)
    revision: int = Field(default=0)

    total_count: int = Field(default=0)
    succeeded_count: int = Field(default=0)
    failed_count: int = Field(default=0)
    pending_count: int = Field(default=0)
    obsolete_reason: str | None = Field(default=None, max_length=64)
    error_code: int | None = Field(default=None)
    error_message: str | None = Field(default=None, sa_column=Column(LargeText, nullable=True))

    # Committed with the job; a scheduler recovers broker publication failures.
    pending_dispatch: bool = Field(default=True)
    dispatch_attempts: int = Field(default=0)
    next_dispatch_at: datetime = Field(default_factory=processing_now)
    dispatch_error_code: int | None = Field(default=None)

    accepted_at: datetime = Field(default_factory=processing_now)
    started_at: datetime | None = Field(default=None)
    finished_at: datetime | None = Field(default=None)
    create_time: datetime = Field(default_factory=processing_now)
    update_time: datetime = Field(default_factory=processing_now)
