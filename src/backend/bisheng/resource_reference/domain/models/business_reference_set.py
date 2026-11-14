"""Source extraction facts and the internal shared multi-version revision latch."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT


class BusinessReferenceSet(SQLModelSerializable, table=True):
    __tablename__ = "business_reference_set"
    __table_args__ = (
        UniqueConstraint("tenant_id", "source_type", "source_id", "source_version", name="uq_brs_source_version"),
        Index("ix_brs_coverage", "tenant_id", "source_type", "record_kind", "ready"),
        CheckConstraint("source_revision >= 0", name="ck_brs_source_revision"),
        CheckConstraint("tenant_id > 0", name="ck_brs_source_tenant"),
        CheckConstraint(
            "(record_kind = 'root_guard' AND source_version = '__root__') OR "
            "(record_kind = 'source' AND source_version <> '__root__')",
            name="ck_brs_record_kind",
        ),
        CheckConstraint("record_kind <> 'root_guard' OR (effective = 0 AND ready = 0)", name="ck_brs_guard_not_source"),
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
    record_kind: str = Field(
        default="source", sa_column=Column(String(16), nullable=False, server_default=text("'source'"))
    )
    source_revision: int = Field(default=0, sa_column=Column(BigInteger, nullable=False, server_default=text("0")))
    extractor_version: str = Field(sa_column=Column(String(64), nullable=False))
    digest: str = Field(sa_column=Column(String(64), nullable=False))
    digest_version: str = Field(
        default="sha256-reference-set-v1",
        sa_column=Column(String(32), nullable=False, server_default=text("'sha256-reference-set-v1'")),
    )
    # Root guard rows are excluded from extraction coverage. Real zero-reference
    # sources still carry a ready row, an extractor version and an empty digest.
    effective: bool = Field(default=True, sa_column=Column(Boolean, nullable=False, server_default=text("1")))
    ready: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, server_default=text("0")))
    create_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    )
    update_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT)
    )
