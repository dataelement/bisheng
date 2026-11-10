"""A saved business configuration slot's target, including registered failures."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, Index, Integer, String, UniqueConstraint, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT


class BusinessResourceReference(SQLModelSerializable, table=True):
    __tablename__ = "business_resource_reference"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "source_type",
            "source_id",
            "source_version",
            "slot_key",
            "target_type",
            "target_id",
            name="uq_brr_source_slot_target",
        ),
        Index("ix_brr_source", "tenant_id", "source_type", "source_id", "source_version"),
        Index("ix_brr_target", "target_type", "target_id"),
        Index("ix_brr_target_space", "target_space_id"),
        CheckConstraint("source_version <> '__root__'", name="ck_brr_real_source"),
        CheckConstraint("source_revision >= 0", name="ck_brr_source_revision"),
        CheckConstraint("tenant_id > 0", name="ck_brr_source_tenant"),
        CheckConstraint("target_tenant_id IS NULL OR target_tenant_id > 0", name="ck_brr_target_tenant"),
        CheckConstraint("target_type IN ('model', 'knowledge_space', 'knowledge_file')", name="ck_brr_target_type"),
        CheckConstraint(
            "(legacy_invalid_reason IS NULL AND legacy_run_id IS NULL AND legacy_evidence_key IS NULL) OR "
            "(legacy_invalid_reason IS NOT NULL AND legacy_invalid_reason = 'target_missing' "
            "AND legacy_run_id IS NOT NULL AND legacy_evidence_key IS NOT NULL)",
            name="ck_brr_legacy_evidence",
        ),
        CheckConstraint(
            "target_tenant_id IS NOT NULL OR (legacy_invalid_reason IS NOT NULL "
            "AND legacy_invalid_reason = 'target_missing' AND legacy_run_id IS NOT NULL "
            "AND legacy_evidence_key IS NOT NULL)",
            name="ck_brr_known_target_owner",
        ),
    )

    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True),
    )
    tenant_id: int | None = Field(
        default=None, sa_column=Column(Integer, nullable=False, server_default=text("1"), index=True)
    )
    source_type: str = Field(sa_column=Column(String(32), nullable=False))
    source_id: str = Field(sa_column=Column(String(64), nullable=False))
    source_version: str = Field(sa_column=Column(String(64), nullable=False))
    slot_key: str = Field(sa_column=Column(String(192), nullable=False))
    target_type: str = Field(sa_column=Column(String(24), nullable=False))
    target_id: str = Field(sa_column=Column(String(64), nullable=False))
    # The original target owner can be unknowable for a frozen legacy missing
    # target. It must never be guessed from this source's tenant_id.
    target_tenant_id: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))
    target_space_id: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    source_revision: int = Field(sa_column=Column(BigInteger, nullable=False))
    legacy_invalid_reason: str | None = Field(default=None, sa_column=Column(String(32), nullable=True))
    legacy_run_id: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    legacy_evidence_key: str | None = Field(default=None, sa_column=Column(String(128), nullable=True))
    create_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    )
    update_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT)
    )
