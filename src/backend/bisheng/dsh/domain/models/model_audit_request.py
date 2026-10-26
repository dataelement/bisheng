"""Tenant-isolated model-audit persistence; no plaintext model bodies."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT, JsonType, PreciseDateTime


class DshModelAuditRequest(SQLModelSerializable, table=True):
    __tablename__ = "dsh_model_audit_request"
    __table_args__ = (
        Index("ix_dma_request_conversation", "tenant_id", "user_id", "conversation_key", "started_at", "request_id"),
        Index("ix_dma_request_time", "tenant_id", "started_at", "request_id"),
        Index("ix_dma_request_model", "tenant_id", "model_id", "started_at", "request_id"),
        Index("ix_dma_request_name", "tenant_id", "model_name_digest", "started_at", "request_id"),
        Index("ix_dma_request_sources", "tenant_id", "message_sources_status", "started_at", "request_id"),
        Index("ix_dma_request_status", "tenant_id", "audit_status", "started_at", "request_id"),
        Index("ix_dma_request_association", "tenant_id", "association_status", "started_at", "request_id"),
        Index("ix_dma_request_group_pending", "tenant_id", "group_index_pending", "request_id"),
        Index("ix_dma_request_tree_pending", "tenant_id", "hierarchy_indexed", "request_id"),
        CheckConstraint("effective_mode IN ('METADATA','CONTENT')", name="ck_dma_request_mode"),
    )
    request_id: str = Field(sa_column=Column(String(36), primary_key=True))

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
    session_id: str = Field(default="", sa_column=Column(String(128), nullable=False))
    model_id: int = Field(default=0, sa_column=Column(BigInteger, nullable=False))
    model_name: str = Field(default="", sa_column=Column(String(2048), nullable=False))
    model_name_digest: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    provider_name: str = Field(default="", sa_column=Column(String(2048), nullable=False))
    conversation_id: str | None = Field(default=None, sa_column=Column(String(1024), nullable=True))
    conversation_key: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    conversation_id_digest: str | None = Field(default=None, sa_column=Column(String(64), nullable=True, index=True))
    request_kind: str | None = Field(default=None, sa_column=Column(String(32), nullable=True))
    session_origin: str | None = Field(default=None, sa_column=Column(String(16), nullable=True))
    parent_conversation_id: str | None = Field(default=None, sa_column=Column(String(1024), nullable=True))
    message_sources_status: str = Field(
        default="NOT_PROVIDED", sa_column=Column(String(16), nullable=False, server_default="NOT_PROVIDED")
    )
    message_sources_ref: dict | None = Field(default=None, sa_column=Column(JsonType, nullable=True))
    association_status: str = Field(default="UNASSOCIATED", sa_column=Column(String(32), nullable=False))
    context_invalid: bool = Field(default=False, sa_column=Column(Boolean, nullable=False))
    effective_mode: str = Field(default="METADATA", sa_column=Column(String(16), nullable=False))
    model_result: str = Field(default="RUNNING", sa_column=Column(String(16), nullable=False))
    response_result: str = Field(default="RUNNING", sa_column=Column(String(16), nullable=False))
    usage_settlement: str = Field(default="PENDING", sa_column=Column(String(16), nullable=False))
    content_status: str = Field(default="NOT_CAPTURED", sa_column=Column(String(16), nullable=False))
    audit_status: str | None = Field(default=None, sa_column=Column(String(16), nullable=True))
    group_index_pending: bool = Field(
        default=False, sa_column=Column(Boolean, nullable=False, server_default=text("0"))
    )
    group_indexed_status: str | None = Field(default=None, sa_column=Column(String(16), nullable=True))
    hierarchy_indexed: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, server_default=text("0")))
    state_version: int = Field(default=0, sa_column=Column(BigInteger, nullable=False))
    input_units: int = Field(default=0, sa_column=Column(BigInteger, nullable=False))
    input_bytes: int = Field(default=0, sa_column=Column(BigInteger, nullable=False))
    output_bytes: int = Field(default=0, sa_column=Column(BigInteger, nullable=False))
    capture_failed: bool = Field(default=False, sa_column=Column(Boolean, nullable=False))

    started_at: datetime = Field(sa_column=Column(PreciseDateTime(), nullable=False))
    model_observed_at: datetime | None = Field(default=None, sa_column=Column(DateTime))
    response_observed_at: datetime | None = Field(default=None, sa_column=Column(DateTime))
    usage_observed_at: datetime | None = Field(default=None, sa_column=Column(DateTime))
    last_write_at: datetime | None = Field(default=None, sa_column=Column(DateTime))


class DshModelAuditEvidence(SQLModelSerializable, table=True):
    __tablename__ = "dsh_model_audit_evidence"
    __table_args__ = (UniqueConstraint("request_id", "event_type", name="uq_dma_evidence"),)
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
    event_type: str = Field(default="MODEL_ENTERED", sa_column=Column(String(32), nullable=False))
    user_id: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    effective_mode: str | None = Field(default=None, sa_column=Column(String(16), nullable=True))
    reason: str | None = Field(default=None, sa_column=Column(String(32), nullable=True))

    observed_at: datetime = Field(sa_column=Column(DateTime, nullable=False))


class DshModelAuditManifest(SQLModelSerializable, table=True):
    __tablename__ = "dsh_model_audit_manifest"
    request_id: str = Field(sa_column=Column(String(36), primary_key=True))

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
    encoding_version: int = Field(default=1, sa_column=Column(BigInteger, nullable=False))
    input_complete: bool = Field(default=False, sa_column=Column(Boolean, nullable=False))
    capture_failed: bool = Field(default=False, sa_column=Column(Boolean, nullable=False))
    model_result: str = Field(default="UNKNOWN", sa_column=Column(String(16), nullable=False))

    channels: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    observed_at: datetime = Field(sa_column=Column(DateTime, nullable=False))
