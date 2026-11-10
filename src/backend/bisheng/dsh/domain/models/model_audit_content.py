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
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT


class DshModelAuditContent(SQLModelSerializable, table=True):
    __tablename__ = "dsh_model_audit_content"
    __table_args__ = (
        UniqueConstraint("scope_key", "encoding_version", "key_version", "digest", name="uq_dma_content"),
        CheckConstraint("scope_type IN ('CONVERSATION','REQUEST')", name="ck_dma_scope"),
    )
    content_id: str = Field(sa_column=Column(String(36), primary_key=True))

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
    user_id: int = Field(default=0, sa_column=Column(BigInteger, nullable=False))
    scope_type: str = Field(default="REQUEST", sa_column=Column(String(16), nullable=False))
    scope_id: str = Field(default="", sa_column=Column(String(1024), nullable=False))
    scope_key: str = Field(default="", sa_column=Column(String(64), nullable=False))
    encoding_version: int = Field(default=1, sa_column=Column(BigInteger, nullable=False))
    key_version: str = Field(default="", sa_column=Column(String(64), nullable=False))
    digest: str = Field(default="", sa_column=Column(String(64), nullable=False))
    byte_length: int = Field(default=0, sa_column=Column(BigInteger, nullable=False))
    object_key: str = Field(default="", sa_column=Column(String(512), nullable=False))
    write_status: str = Field(default="READY", sa_column=Column(String(16), nullable=False))


class DshModelAuditOccurrence(SQLModelSerializable, table=True):
    __tablename__ = "dsh_model_audit_occurrence"
    __table_args__ = (UniqueConstraint("request_id", "stage", "channel", "sequence", name="uq_dma_occurrence"),)
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
    request_id: str = Field(default="", sa_column=Column(String(36), nullable=False))
    stage: str = Field(default="MODEL", sa_column=Column(String(16), nullable=False))
    channel: str = Field(default="input", sa_column=Column(String(16), nullable=False))
    sequence: int = Field(default=0, sa_column=Column(BigInteger, nullable=False))
    unit_index: int = Field(default=0, sa_column=Column(BigInteger, nullable=False))
    byte_length: int = Field(default=0, sa_column=Column(BigInteger, nullable=False))
    digest: str = Field(default="", sa_column=Column(String(64), nullable=False))
    content_id: str = Field(default="", sa_column=Column(String(36), nullable=False))


class DshModelAuditBodyAccess(SQLModelSerializable, table=True):
    __tablename__ = "dsh_model_audit_body_access"
    access_id: str = Field(default_factory=lambda: str(uuid4()), sa_column=Column(String(36), primary_key=True))

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
    request_id: str = Field(default="", sa_column=Column(String(36), nullable=False))
    trace_id: str = Field(default="", sa_column=Column(String(36), nullable=False))
    result: str = Field(default="AUTHORIZED", sa_column=Column(String(24), nullable=False))
    transfer_status: str | None = Field(default=None, sa_column=Column(String(24), nullable=True))
