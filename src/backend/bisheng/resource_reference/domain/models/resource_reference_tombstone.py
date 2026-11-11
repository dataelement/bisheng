"""Real target deletion evidence; legacy missing targets never create this row."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, Index, Integer, String, UniqueConstraint, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT


class ResourceReferenceTombstone(SQLModelSerializable, table=True):
    __tablename__ = "resource_reference_tombstone"
    __table_args__ = (
        UniqueConstraint("target_type", "target_id", "target_tenant_id", name="uq_rrt_target_owner"),
        Index("ix_rrt_operation", "tenant_id", "operation_id"),
        CheckConstraint("target_type IN ('model', 'knowledge_space', 'knowledge_file')", name="ck_rrt_target_type"),
        CheckConstraint("stage IN ('deleting', 'deleted')", name="ck_rrt_stage"),
        CheckConstraint("tenant_id > 0 AND target_tenant_id = tenant_id", name="ck_rrt_target_owner"),
    )

    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True),
    )
    # Automatic isolation follows the real deleted target owner, not a source
    # tenant that happens to reference a shared target.
    tenant_id: int | None = Field(
        default=None, sa_column=Column(Integer, nullable=False, server_default=text("1"), index=True)
    )
    target_type: str = Field(sa_column=Column(String(24), nullable=False))
    target_id: str = Field(sa_column=Column(String(64), nullable=False))
    target_tenant_id: int = Field(sa_column=Column(Integer, nullable=False))
    operation_id: str = Field(sa_column=Column(String(64), nullable=False))
    operation_type: str = Field(sa_column=Column(String(32), nullable=False))
    stage: str = Field(
        default="deleting", sa_column=Column(String(16), nullable=False, server_default=text("'deleting'"))
    )
    actor_type: str = Field(sa_column=Column(String(32), nullable=False))
    actor_id: str = Field(sa_column=Column(String(64), nullable=False))
    deleted_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    create_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    )
    update_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT)
    )
