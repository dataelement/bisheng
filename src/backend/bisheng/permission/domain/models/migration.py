"""Authorization-model release and F048 data-migration audit models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CHAR,
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT


class AuthorizationModelReleaseStatus(StrEnum):
    STAGED = "STAGED"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"
    FAILED_CLOSED = "FAILED_CLOSED"


class PermissionMigrationStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    BLOCKED = "BLOCKED"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED_CLOSED = "FAILED_CLOSED"


class PermissionMigrationItemStatus(StrEnum):
    PENDING = "PENDING"
    MIGRATED = "MIGRATED"
    VERIFIED = "VERIFIED"
    SKIPPED = "SKIPPED"
    MANUAL = "MANUAL"
    BLOCKED = "BLOCKED"
    FAILED_CLOSED = "FAILED_CLOSED"


class AuthorizationModelRelease(SQLModelSerializable, table=True):
    __tablename__ = "authorization_model_release"
    __table_args__ = (
        UniqueConstraint(
            "environment",
            "store_id",
            "model_id",
            name="uq_auth_model_release",
        ),
        Index(
            "ix_auth_model_release_status",
            "environment",
            "status",
            "activated_at",
        ),
    )

    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    environment: str = Field(sa_column=Column(String(64), nullable=False))
    store_id: str = Field(sa_column=Column(String(64), nullable=False))
    model_version: str = Field(sa_column=Column(String(64), nullable=False))
    model_id: str = Field(sa_column=Column(String(64), nullable=False))
    predecessor_model_id: str | None = Field(
        default=None,
        sa_column=Column(String(64), nullable=True),
    )
    model_checksum: str = Field(sa_column=Column(CHAR(64), nullable=False))
    required_relations_checksum: str = Field(
        sa_column=Column(CHAR(64), nullable=False),
    )
    openfga_version: str = Field(sa_column=Column(String(64), nullable=False))
    status: str = Field(
        default=AuthorizationModelReleaseStatus.STAGED.value,
        sa_column=Column(String(64), nullable=False, server_default=text("'STAGED'")),
    )
    activated_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=True),
    )
    retired_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=True),
    )
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
        ),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=UPDATE_TIME_SERVER_DEFAULT,
        ),
    )


class PermissionMigrationRun(SQLModelSerializable, table=True):
    __tablename__ = "permission_migration_run"
    __table_args__ = (
        UniqueConstraint(
            "environment_fingerprint",
            name="uq_perm_migration_environment",
        ),
        Index(
            "ix_perm_migration_run_status",
            "status",
            "update_time",
            "id",
        ),
    )

    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    environment_fingerprint: str = Field(sa_column=Column(CHAR(64), nullable=False))
    phase: str = Field(sa_column=Column(String(64), nullable=False))
    status: str = Field(
        default=PermissionMigrationStatus.PENDING.value,
        sa_column=Column(String(64), nullable=False, server_default=text("'PENDING'")),
    )
    store_id: str = Field(sa_column=Column(String(64), nullable=False))
    source_model_id: str = Field(sa_column=Column(String(64), nullable=False))
    target_model_id: str | None = Field(
        default=None,
        sa_column=Column(String(64), nullable=True),
    )
    source_watermark: str | None = Field(
        default=None,
        sa_column=Column(String(256), nullable=True),
    )
    checkpoint: str | None = Field(
        default=None,
        sa_column=Column(String(256), nullable=True),
    )
    source_checksum: str | None = Field(
        default=None,
        sa_column=Column(CHAR(64), nullable=True),
    )
    target_checksum: str | None = Field(
        default=None,
        sa_column=Column(CHAR(64), nullable=True),
    )
    scanned_count: int = Field(
        default=0,
        sa_column=Column(BigInteger, nullable=False, server_default=text("0")),
    )
    migrated_count: int = Field(
        default=0,
        sa_column=Column(BigInteger, nullable=False, server_default=text("0")),
    )
    skipped_count: int = Field(
        default=0,
        sa_column=Column(BigInteger, nullable=False, server_default=text("0")),
    )
    blocker_count: int = Field(
        default=0,
        sa_column=Column(BigInteger, nullable=False, server_default=text("0")),
    )
    manual_count: int = Field(
        default=0,
        sa_column=Column(BigInteger, nullable=False, server_default=text("0")),
    )
    error_count: int = Field(
        default=0,
        sa_column=Column(BigInteger, nullable=False, server_default=text("0")),
    )
    report_uri: str | None = Field(
        default=None,
        sa_column=Column(String(512), nullable=True),
    )
    report_checksum: str | None = Field(
        default=None,
        sa_column=Column(CHAR(64), nullable=True),
    )
    lock_token: str | None = Field(
        default=None,
        sa_column=Column(String(64), nullable=True),
    )
    lock_expires_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=True),
    )
    version: int = Field(
        default=1,
        sa_column=Column(BigInteger, nullable=False, server_default=text("1")),
    )
    manual_review_status: str = Field(
        default="NOT_REQUIRED",
        sa_column=Column(
            String(64),
            nullable=False,
            server_default=text("'NOT_REQUIRED'"),
        ),
    )
    approved_by: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, nullable=True),
    )
    approved_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=True),
    )
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
        ),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=UPDATE_TIME_SERVER_DEFAULT,
        ),
    )


class PermissionMigrationItem(SQLModelSerializable, table=True):
    __tablename__ = "permission_migration_item"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "source_kind",
            "source_locator",
            name="uq_perm_migration_item_source",
        ),
        Index(
            "ix_perm_migration_item_resume",
            "run_id",
            "status",
            "id",
        ),
        Index(
            "ix_perm_migration_item_diff",
            "run_id",
            "severity",
            "difference_type",
        ),
    )

    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    run_id: int = Field(
        sa_column=Column(
            BigInteger,
            ForeignKey("permission_migration_run.id", ondelete="RESTRICT"),
            nullable=False,
        ),
    )
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, nullable=True, index=True),
    )
    source_kind: str = Field(sa_column=Column(String(64), nullable=False))
    source_locator: str = Field(sa_column=Column(String(256), nullable=False))
    source_checksum: str = Field(sa_column=Column(CHAR(64), nullable=False))
    target_kind: str | None = Field(
        default=None,
        sa_column=Column(String(64), nullable=True),
    )
    target_id: str | None = Field(
        default=None,
        sa_column=Column(String(64), nullable=True),
    )
    target_checksum: str | None = Field(
        default=None,
        sa_column=Column(CHAR(64), nullable=True),
    )
    status: str = Field(
        default=PermissionMigrationItemStatus.PENDING.value,
        sa_column=Column(String(64), nullable=False, server_default=text("'PENDING'")),
    )
    severity: str = Field(sa_column=Column(String(64), nullable=False))
    difference_type: str | None = Field(
        default=None,
        sa_column=Column(String(64), nullable=True),
    )
    message: str | None = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    manual_action: str | None = Field(
        default=None,
        sa_column=Column(String(64), nullable=True),
    )
    approved_by: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, nullable=True),
    )
    approved_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=True),
    )
    retry_count: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text("0")),
    )
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
        ),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=UPDATE_TIME_SERVER_DEFAULT,
        ),
    )
