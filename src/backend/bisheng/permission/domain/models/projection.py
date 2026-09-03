"""Durable SQL-to-OpenFGA projection ledger models."""

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
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT


class ProjectionOperationStatus(StrEnum):
    PREPARED = "PREPARED"
    STAGING = "STAGING"
    COMMIT_UNKNOWN = "COMMIT_UNKNOWN"
    COMMITTED = "COMMITTED"
    FINALIZED = "FINALIZED"
    FAILED_CLOSED = "FAILED_CLOSED"


class ProjectionTupleStatus(StrEnum):
    PENDING = "PENDING"
    APPLIED = "APPLIED"
    VERIFIED = "VERIFIED"
    COMPENSATED = "COMPENSATED"
    FAILED_CLOSED = "FAILED_CLOSED"


class VisibleSourceProjectionState(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"
    FAILED_CLOSED = "FAILED_CLOSED"


class PermissionProjectionOperation(SQLModelSerializable, table=True):
    __tablename__ = "permission_projection_operation"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_perm_projection_idempotency",
        ),
        Index(
            "ix_perm_projection_retry",
            "status",
            "update_time",
            "id",
        ),
        Index(
            "ix_perm_projection_scope",
            "tenant_id",
            "scope_type",
            "scope_key",
            "status",
        ),
    )

    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, nullable=False, index=True),
    )
    idempotency_key: str = Field(sa_column=Column(String(64), nullable=False))
    request_checksum: str = Field(sa_column=Column(CHAR(64), nullable=False))
    operation_type: str = Field(sa_column=Column(String(64), nullable=False))
    scope_type: str = Field(sa_column=Column(String(64), nullable=False))
    scope_key: str = Field(sa_column=Column(String(256), nullable=False))
    expected_version: int = Field(sa_column=Column(BigInteger, nullable=False))
    target_version: int = Field(sa_column=Column(BigInteger, nullable=False))
    store_id: str = Field(sa_column=Column(String(64), nullable=False))
    model_id: str = Field(sa_column=Column(String(64), nullable=False))
    status: str = Field(
        default=ProjectionOperationStatus.PREPARED.value,
        sa_column=Column(String(64), nullable=False, server_default=text("'PREPARED'")),
    )
    before_checksum: str = Field(sa_column=Column(CHAR(64), nullable=False))
    after_checksum: str = Field(sa_column=Column(CHAR(64), nullable=False))
    commit_checksum: str | None = Field(
        default=None,
        sa_column=Column(CHAR(64), nullable=True),
    )
    operator_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    error_code: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, nullable=True),
    )
    error_message: str | None = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
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


class PermissionProjectionTuple(SQLModelSerializable, table=True):
    __tablename__ = "permission_projection_tuple"
    __table_args__ = (
        UniqueConstraint(
            "operation_id",
            "phase",
            "tuple_fingerprint",
            name="uq_perm_projection_tuple",
        ),
        Index(
            "ix_perm_projection_tuple_status",
            "operation_id",
            "status",
            "sequence",
        ),
    )

    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, nullable=False, index=True),
    )
    operation_id: int | None = Field(
        default=None,
        sa_column=Column(
            BigInteger,
            ForeignKey("permission_projection_operation.id", ondelete="RESTRICT"),
            nullable=False,
        ),
    )
    phase: str = Field(sa_column=Column(String(64), nullable=False))
    sequence: int = Field(sa_column=Column(BigInteger, nullable=False))
    action: str = Field(sa_column=Column(String(64), nullable=False))
    fga_user: str = Field(sa_column=Column(String(256), nullable=False))
    relation: str = Field(sa_column=Column(String(64), nullable=False))
    fga_object: str = Field(sa_column=Column(String(256), nullable=False))
    tuple_fingerprint: str = Field(sa_column=Column(CHAR(64), nullable=False))
    inverse_action: str = Field(sa_column=Column(String(64), nullable=False))
    status: str = Field(
        default=ProjectionTupleStatus.PENDING.value,
        sa_column=Column(String(64), nullable=False, server_default=text("'PENDING'")),
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


class PermissionVisibleSourceProjection(SQLModelSerializable, table=True):
    """Rebuildable source index for one flattened visible relation."""

    __tablename__ = "permission_visible_source_projection"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "resource_type",
            "resource_id",
            "visibility_class",
            "projected_subject",
            "contribution_fingerprint",
            name="uq_perm_visible_source_contribution",
        ),
        Index(
            "ix_perm_visible_resource_subject",
            "tenant_id",
            "resource_type",
            "resource_id",
            "visibility_class",
            "projected_subject",
            "state",
        ),
        Index(
            "ix_perm_visible_model_state",
            "model_key",
            "state",
            "tenant_id",
            "id",
        ),
        Index(
            "ix_perm_visible_source_owner",
            "tenant_id",
            "source_kind",
            "source_owner_key",
            "state",
            "id",
        ),
        Index(
            "ix_perm_visible_operation",
            "tenant_id",
            "operation_id",
            "state",
            "id",
        ),
        Index(
            "ix_perm_visible_migration_item",
            "migration_item_id",
            "state",
            "id",
        ),
    )

    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, nullable=False, index=True),
    )
    resource_type: str = Field(sa_column=Column(String(64), nullable=False))
    resource_id: str = Field(sa_column=Column(String(64), nullable=False))
    visibility_class: str = Field(sa_column=Column(String(64), nullable=False))
    projected_subject: str = Field(sa_column=Column(String(256), nullable=False))
    source_kind: str = Field(sa_column=Column(String(64), nullable=False))
    source_owner_key: str = Field(sa_column=Column(String(256), nullable=False))
    source_locator: str = Field(sa_column=Column(String(256), nullable=False))
    source_fingerprint: str = Field(sa_column=Column(CHAR(64), nullable=False))
    contribution_fingerprint: str = Field(sa_column=Column(CHAR(64), nullable=False))
    model_key: str | None = Field(
        default=None,
        sa_column=Column(String(64), nullable=True),
    )
    source_version: int = Field(sa_column=Column(BigInteger, nullable=False))
    tuple_fingerprint: str = Field(sa_column=Column(CHAR(64), nullable=False))
    state: str = Field(
        default=VisibleSourceProjectionState.PENDING.value,
        sa_column=Column(String(64), nullable=False, server_default=text("'PENDING'")),
    )
    operation_id: int | None = Field(
        default=None,
        sa_column=Column(
            BigInteger,
            ForeignKey("permission_projection_operation.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    migration_item_id: int | None = Field(
        default=None,
        sa_column=Column(
            BigInteger,
            ForeignKey("permission_migration_item.id", ondelete="RESTRICT"),
            nullable=True,
        ),
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
