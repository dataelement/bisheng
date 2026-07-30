"""Tenant-scoped F048 Grant, assignee, and resource-mode models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT


class GrantState(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    FAILED_CLOSED = "FAILED_CLOSED"


class ProjectionState(StrEnum):
    PENDING = "PENDING"
    PROJECTING = "PROJECTING"
    CURRENT = "CURRENT"
    FAILED_CLOSED = "FAILED_CLOSED"


class PermissionGrant(SQLModelSerializable, table=True):
    __tablename__ = "permission_grant"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "resource_type",
            "resource_id",
            "model_key",
            name="uq_perm_grant_resource_model",
        ),
        Index(
            "ix_perm_grant_resource_state",
            "tenant_id",
            "resource_type",
            "resource_id",
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
    model_key: str = Field(sa_column=Column(String(64), nullable=False))
    state: str = Field(
        default=GrantState.PENDING.value,
        sa_column=Column(String(64), nullable=False, server_default=text("'PENDING'")),
    )
    version: int = Field(
        default=1,
        sa_column=Column(BigInteger, nullable=False, server_default=text("1")),
    )
    projection_state: str = Field(
        default=ProjectionState.PENDING.value,
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


class PermissionGrantAssignee(SQLModelSerializable, table=True):
    __tablename__ = "permission_grant_assignee"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "grant_id",
            "source_fingerprint",
            name="uq_perm_assignee_source",
        ),
        Index(
            "ix_perm_assignee_grant_state",
            "tenant_id",
            "grant_id",
            "state",
            "id",
        ),
        Index(
            "ix_perm_assignee_subject_state",
            "tenant_id",
            "subject_type",
            "subject_id",
            "state",
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
    grant_id: int = Field(
        sa_column=Column(
            BigInteger,
            ForeignKey("permission_grant.id", ondelete="RESTRICT"),
            nullable=False,
        ),
    )
    subject_type: str = Field(sa_column=Column(String(64), nullable=False))
    subject_id: str = Field(sa_column=Column(String(64), nullable=False))
    userset_relation: str | None = Field(
        default=None,
        sa_column=Column(String(64), nullable=True),
    )
    include_children: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("0")),
    )
    source_type: str = Field(sa_column=Column(String(64), nullable=False))
    source_ref: str = Field(sa_column=Column(String(256), nullable=False))
    source_locator: str = Field(sa_column=Column(String(256), nullable=False))
    source_fingerprint: str = Field(sa_column=Column(CHAR(64), nullable=False))
    projected_subject: str = Field(sa_column=Column(String(256), nullable=False))
    protected: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("0")),
    )
    state: str = Field(
        default=GrantState.PENDING.value,
        sa_column=Column(String(64), nullable=False, server_default=text("'PENDING'")),
    )
    version: int = Field(
        default=1,
        sa_column=Column(BigInteger, nullable=False, server_default=text("1")),
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


class ResourcePermissionMode(SQLModelSerializable, table=True):
    __tablename__ = "resource_permission_mode"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "resource_type",
            "resource_id",
            name="uq_resource_permission_mode",
        ),
        Index(
            "ix_resource_mode_projection",
            "tenant_id",
            "projection_state",
            "update_time",
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
    mode: str = Field(sa_column=Column(String(64), nullable=False))
    parent_type: str | None = Field(
        default=None,
        sa_column=Column(String(64), nullable=True),
    )
    parent_id: str | None = Field(
        default=None,
        sa_column=Column(String(64), nullable=True),
    )
    version: int = Field(
        default=1,
        sa_column=Column(BigInteger, nullable=False, server_default=text("1")),
    )
    projection_state: str = Field(
        default=ProjectionState.PENDING.value,
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
