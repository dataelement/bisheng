"""Tenant-isolated model-audit persistence; no plaintext model bodies."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    String,
    UniqueConstraint,
    text,
)
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT, PreciseDateTime


class DshModelAuditSetting(SQLModelSerializable, table=True):
    __tablename__ = "dsh_model_audit_setting"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_dma_setting_tenant"),
        CheckConstraint("mode IN ('OFF','METADATA','CONTENT')", name="ck_dma_setting_mode"),
    )
    id: str = Field(default_factory=lambda: str(uuid4()), sa_column=Column(String(36), primary_key=True))

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
    mode: str = Field(default="OFF", sa_column=Column(String(16), nullable=False))
    version: int = Field(default=0, sa_column=Column(BigInteger, nullable=False))
    audit_deleted_before: datetime | None = Field(default=None, sa_column=Column(PreciseDateTime()))
    cleanup_before: datetime | None = Field(default=None, sa_column=Column(PreciseDateTime()))
    cleanup_after_started_at: datetime | None = Field(default=None, sa_column=Column(PreciseDateTime()))
    cleanup_after_request_id: str | None = Field(default=None, sa_column=Column(String(36)))
    updated_by: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))


class DshModelAuditSettingChange(SQLModelSerializable, table=True):
    __tablename__ = "dsh_model_audit_setting_change"
    __table_args__ = (UniqueConstraint("tenant_id", "operation_id", name="uq_dma_setting_operation"),)
    operation_id: str = Field(sa_column=Column(String(36), primary_key=True))

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
    actor_user_id: int = Field(default=0, sa_column=Column(BigInteger, nullable=False))
    before_mode: str = Field(default="OFF", sa_column=Column(String(16), nullable=False))
    after_mode: str = Field(default="OFF", sa_column=Column(String(16), nullable=False))
    expected_version: int = Field(default=0, sa_column=Column(BigInteger, nullable=False))
    result_version: int = Field(default=0, sa_column=Column(BigInteger, nullable=False))
