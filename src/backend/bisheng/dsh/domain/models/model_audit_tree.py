"""Disposable metadata-only tree generations; originals remain in their own conversations."""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Index, String, UniqueConstraint, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT, PreciseDateTime


class DshAuditTreeState(SQLModelSerializable, table=True):
    __tablename__ = "dsh_audit_tree_state"
    tenant_id: int = Field(sa_column=Column(BigInteger, primary_key=True, index=True))
    create_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT, onupdate=text("CURRENT_TIMESTAMP")
        ),
    )
    revision: int = Field(default=0, sa_column=Column(BigInteger, nullable=False))
    summary_revision: int = Field(default=0, sa_column=Column(BigInteger, nullable=False))
    published_revision: int = Field(default=-1, sa_column=Column(BigInteger, nullable=False))
    published_summary_revision: int = Field(default=-1, sa_column=Column(BigInteger, nullable=False))
    build_revision: int = Field(default=0, sa_column=Column(BigInteger, nullable=False))
    build_summary_revision: int = Field(default=0, sa_column=Column(BigInteger, nullable=False))
    active: str | None = Field(default=None, sa_column=Column(String(36)))
    retired: str | None = Field(default=None, sa_column=Column(String(36)))
    building: str | None = Field(default=None, sa_column=Column(String(36)))
    phase: str = Field(default="IDLE", sa_column=Column(String(16), nullable=False))
    after_key: str = Field(default="", sa_column=Column(String(64), nullable=False))
    lease_owner: str | None = Field(default=None, sa_column=Column(String(36)))
    lease_until: datetime | None = Field(default=None, sa_column=Column(PreciseDateTime()))
    published_at: datetime | None = Field(default=None, sa_column=Column(PreciseDateTime()))
    failed: bool = Field(default=False, sa_column=Column(Boolean, nullable=False))


class DshAuditTreeNode(SQLModelSerializable, table=True):
    __tablename__ = "dsh_audit_tree_node"
    __table_args__ = (
        UniqueConstraint("tenant_id", "generation", "conversation_key", name="uq_dat_node"),
        Index("ix_dat_parent", "tenant_id", "generation", "parent_key", "listed_at", "conversation_key"),
        Index(
            "ix_dat_user_parent", "tenant_id", "generation", "user_id", "parent_key", "listed_at", "conversation_key"
        ),
        Index("ix_dat_build", "tenant_id", "generation", "conversation_key"),
    )
    id: str = Field(sa_column=Column(String(64), primary_key=True))
    tenant_id: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=False, index=True))
    create_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT, onupdate=text("CURRENT_TIMESTAMP")
        ),
    )
    generation: str = Field(sa_column=Column(String(36), nullable=False))
    conversation_key: str = Field(sa_column=Column(String(64), nullable=False))
    conversation_id: str = Field(sa_column=Column(String(1024), nullable=False))
    user_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    declared_parent_key: str | None = Field(default=None, sa_column=Column(String(64)))
    origin_state: str = Field(default="UNKNOWN", sa_column=Column(String(16), nullable=False))
    relation_conflict: bool = Field(default=False, sa_column=Column(Boolean, nullable=False))
    parent_key: str = Field(default="", sa_column=Column(String(64), nullable=False))
    root_key: str = Field(default="", sa_column=Column(String(64), nullable=False))
    relation_state: str = Field(default="PENDING", sa_column=Column(String(24), nullable=False))
    listed_at: datetime = Field(sa_column=Column(PreciseDateTime(), nullable=False))
    last_request_at: datetime = Field(sa_column=Column(PreciseDateTime(), nullable=False))
    updated_at: datetime = Field(sa_column=Column(PreciseDateTime(), nullable=False))
    request_count: int = Field(sa_column=Column(BigInteger, nullable=False))
    abnormal_count: int = Field(sa_column=Column(BigInteger, nullable=False))
    branch_count: int = Field(default=0, sa_column=Column(BigInteger, nullable=False))
    branch_abnormal: int = Field(default=0, sa_column=Column(BigInteger, nullable=False))


class DshAuditTreePath(SQLModelSerializable, table=True):
    __tablename__ = "dsh_audit_tree_path"
    __table_args__ = (
        UniqueConstraint("tenant_id", "generation", "ancestor_key", "descendant_key", name="uq_dat_path"),
        Index("ix_dat_ancestor", "tenant_id", "generation", "ancestor_key", "descendant_key"),
        Index("ix_dat_descendant", "tenant_id", "generation", "descendant_key", "depth"),
    )
    id: str = Field(sa_column=Column(String(64), primary_key=True))
    tenant_id: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=False, index=True))
    create_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT, onupdate=text("CURRENT_TIMESTAMP")
        ),
    )
    generation: str = Field(sa_column=Column(String(36), nullable=False))
    user_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    ancestor_key: str = Field(sa_column=Column(String(64), nullable=False))
    descendant_key: str = Field(sa_column=Column(String(64), nullable=False))
    depth: int = Field(sa_column=Column(BigInteger, nullable=False))
