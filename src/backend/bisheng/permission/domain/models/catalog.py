"""Global F048 permission Catalog ORM models."""

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
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT


class CatalogReleaseStatus(StrEnum):
    DRAFT = "DRAFT"
    PROJECTING = "PROJECTING"
    COMMITTED = "COMMITTED"
    CURRENT = "CURRENT"
    RETIRED = "RETIRED"
    FAILED_CLOSED = "FAILED_CLOSED"


class PermissionCatalogRelease(SQLModelSerializable, table=True):
    __tablename__ = "permission_catalog_release"
    __table_args__ = (
        UniqueConstraint("release_key", name="uq_perm_catalog_release_key"),
        UniqueConstraint("version", name="uq_perm_catalog_version"),
        UniqueConstraint("idempotency_key", name="uq_perm_catalog_idempotency"),
        Index("ix_perm_catalog_status_version", "status", "version"),
    )

    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    release_key: str = Field(sa_column=Column(String(64), nullable=False))
    version: int = Field(sa_column=Column(BigInteger, nullable=False))
    status: str = Field(
        default=CatalogReleaseStatus.DRAFT.value,
        sa_column=Column(String(64), nullable=False, server_default=text("'DRAFT'")),
    )
    write_fenced: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("0")),
    )
    predecessor_id: int | None = Field(
        default=None,
        sa_column=Column(
            BigInteger,
            ForeignKey("permission_catalog_release.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    required_authorization_model_release_id: int = Field(
        sa_column=Column(
            BigInteger,
            ForeignKey("authorization_model_release.id", ondelete="RESTRICT"),
            nullable=False,
        ),
    )
    draft_owner_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    idempotency_key: str = Field(sa_column=Column(String(64), nullable=False))
    projection_checkpoint: int = Field(
        default=0,
        sa_column=Column(BigInteger, nullable=False, server_default=text("0")),
    )
    expires_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=True),
    )
    published_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=True),
    )
    checksum: str = Field(sa_column=Column(CHAR(64), nullable=False))
    commit_checksum: str | None = Field(
        default=None,
        sa_column=Column(CHAR(64), nullable=True),
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


class PermissionAction(SQLModelSerializable, table=True):
    __tablename__ = "permission_action"
    __table_args__ = (
        UniqueConstraint(
            "catalog_release_id",
            "code",
            name="uq_perm_action_release_code",
        ),
        Index("ix_perm_action_release_active", "catalog_release_id", "active"),
    )

    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    catalog_release_id: int = Field(
        sa_column=Column(
            BigInteger,
            ForeignKey("permission_catalog_release.id", ondelete="RESTRICT"),
            nullable=False,
        ),
    )
    code: str = Field(sa_column=Column(String(64), nullable=False))
    name: str = Field(sa_column=Column(String(255), nullable=False))
    level: int | None = Field(
        default=None,
        sa_column=Column(Integer, nullable=True),
    )
    active: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default=text("1")),
    )
    sort_order: int = Field(
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


class PermissionActionResourceScope(SQLModelSerializable, table=True):
    __tablename__ = "permission_action_resource_scope"
    __table_args__ = (
        UniqueConstraint(
            "action_id",
            "resource_type",
            name="uq_perm_action_resource_scope",
        ),
    )

    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    action_id: int = Field(
        sa_column=Column(
            BigInteger,
            ForeignKey("permission_action.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
    )
    resource_type: str = Field(sa_column=Column(String(64), nullable=False))
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


class PermissionModel(SQLModelSerializable, table=True):
    __tablename__ = "permission_model"
    __table_args__ = (
        UniqueConstraint(
            "catalog_release_id",
            "model_key",
            name="uq_perm_model_release_key",
        ),
        UniqueConstraint(
            "catalog_release_id",
            "normalized_name",
            name="uq_perm_model_release_name",
        ),
        Index("ix_perm_model_release_active", "catalog_release_id", "active"),
    )

    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    catalog_release_id: int = Field(
        sa_column=Column(
            BigInteger,
            ForeignKey("permission_catalog_release.id", ondelete="RESTRICT"),
            nullable=False,
        ),
    )
    model_key: str = Field(sa_column=Column(String(64), nullable=False))
    normalized_name: str = Field(sa_column=Column(String(255), nullable=False))
    name: str = Field(sa_column=Column(String(255), nullable=False))
    kind: str = Field(sa_column=Column(String(64), nullable=False))
    config_scope: str = Field(
        default="PLATFORM",
        sa_column=Column(
            String(64),
            nullable=False,
            server_default=text("'PLATFORM'"),
        ),
    )
    derived_level: int | None = Field(
        default=None,
        sa_column=Column(Integer, nullable=True),
    )
    active: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default=text("1")),
    )
    allow_same_level: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("0")),
    )
    legacy_source_key: str | None = Field(
        default=None,
        sa_column=Column(String(64), nullable=True),
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


class PermissionModelAction(SQLModelSerializable, table=True):
    __tablename__ = "permission_model_action"
    __table_args__ = (
        UniqueConstraint(
            "model_id",
            "action_id",
            name="uq_perm_model_action",
        ),
    )

    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    model_id: int = Field(
        sa_column=Column(
            BigInteger,
            ForeignKey("permission_model.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
    )
    action_id: int = Field(
        sa_column=Column(
            BigInteger,
            ForeignKey("permission_action.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
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


class PermissionCatalogProjectionTuple(SQLModelSerializable, table=True):
    __tablename__ = "permission_catalog_projection_tuple"
    __table_args__ = (
        UniqueConstraint(
            "catalog_release_id",
            "phase",
            "tuple_fingerprint",
            name="uq_perm_catalog_tuple",
        ),
        Index(
            "ix_perm_catalog_tuple_status",
            "catalog_release_id",
            "status",
            "sequence",
        ),
    )

    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    catalog_release_id: int = Field(
        sa_column=Column(
            BigInteger,
            ForeignKey("permission_catalog_release.id", ondelete="RESTRICT"),
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
    status: str = Field(sa_column=Column(String(64), nullable=False))
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
