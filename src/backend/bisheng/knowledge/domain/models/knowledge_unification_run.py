"""Tenant-scoped, resumable maintenance facts and reference-coverage readiness.

Large frozen inventories/plans live in durable object storage; these rows keep
their immutable locator/hash and checkpoints, never process-local file paths.
Empty-tenant initialization is explicitly distinct from a migration baseline.
"""

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import BigInteger, CheckConstraint, Column, Index, Integer, UniqueConstraint, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import JsonType


def unification_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class KnowledgeUnificationPhase(StrEnum):
    PREPARING = "preparing"
    BASELINE_FROZEN = "baseline_frozen"
    CONVERTING = "converting"
    BACKFILLING = "backfilling"
    VERIFYING = "verifying"
    VERIFIED = "verified"
    COMPLETED = "completed"
    FAILED = "failed"


# Once frozen, provenance survives the remaining successful migration phases.
# A failed run cannot serve online proof until its explicit recovery succeeds.
FROZEN_BASELINE_PHASES = frozenset(
    phase.value
    for phase in KnowledgeUnificationPhase
    if phase not in (KnowledgeUnificationPhase.PREPARING, KnowledgeUnificationPhase.FAILED)
)


class KnowledgeUnificationRun(SQLModelSerializable, table=True):
    __tablename__ = "knowledge_unification_run"
    __table_args__ = (
        UniqueConstraint("tenant_id", "run_id", name="uq_kun_run_tenant"),
        Index("ix_kun_coverage", "tenant_id", "writer_contract_version", "phase", "id"),
        Index("ix_kun_coverage_epoch", "writer_contract_version", "coverage_epoch", "tenant_id"),
        CheckConstraint("origin IN ('migration', 'empty_tenant')", name="ck_kun_origin"),
        CheckConstraint("tenant_id > 0", name="ck_kun_tenant"),
    )

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True, max_length=36)
    tenant_id: int | None = Field(
        default=None, sa_column=Column(Integer, nullable=False, server_default=text("1"), index=True)
    )
    run_id: str = Field(max_length=64, index=True)
    origin: str = Field(default="migration", max_length=24)
    phase: str = Field(default="preparing", max_length=32)
    writer_contract_version: str = Field(default="f118-v1", max_length=32)
    baseline_hash: str | None = Field(default=None, max_length=64)
    plan_hash: str | None = Field(default=None, max_length=64)
    # Durable object key, digest and size/count. No credential, signed URL or
    # unfrozen full business configuration is copied into the ledger.
    baseline_ref: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    plan_ref: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    checkpoints: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    source_coverage: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    coverage_epoch: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    verification_report: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    error_code: int | None = Field(default=None)
    error_reason: str | None = Field(default=None, max_length=128)
    create_time: datetime = Field(default_factory=unification_now)
    update_time: datetime = Field(default_factory=unification_now)
