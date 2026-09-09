"""F062 model call persistence model."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, Index, String, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT


class DshModelCall(SQLModelSerializable, table=True):
    """Full request state; NULL usage is unresolved, never free usage."""

    __tablename__ = "dsh_model_call"
    __table_args__ = (
        Index("ix_dsh_call_user_started", "tenant_id", "user_id", "started_at"),
        Index("ix_dsh_call_model_started", "tenant_id", "user_id", "model_id", "started_at"),
        Index("ix_dsh_call_status_updated", "status", "update_time"),
        Index("ix_dsh_call_trace", "trace_id"),
        CheckConstraint(
            "status IN ('RUNNING','SUCCEEDED','FAILED','CANCELLED','USAGE_UNKNOWN')", name="ck_dsh_call_status"
        ),
        CheckConstraint("usage_source IS NULL OR usage_source IN ('PROVIDER','RECONCILED')", name="ck_dsh_call_source"),
        CheckConstraint(
            "(input_tokens IS NULL AND output_tokens IS NULL AND total_tokens IS NULL) OR (input_tokens IS NOT NULL AND output_tokens IS NOT NULL AND total_tokens IS NOT NULL AND input_tokens >= 0 AND output_tokens >= 0 AND total_tokens = input_tokens + output_tokens)",
            name="ck_dsh_call_usage",
        ),
        CheckConstraint(
            "grant_version >= 1 AND event_version >= 1 AND quota_epoch >= 1 AND policy_version >= 1",
            name="ck_dsh_call_versions",
        ),
    )
    request_id: str = Field(sa_column=Column(String(36), primary_key=True))
    tenant_id: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=False, index=True))
    user_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    create_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT, onupdate=text("CURRENT_TIMESTAMP")
        ),
    )
    seat_id: str = Field(sa_column=Column(String(36), nullable=False))
    session_id: str = Field(sa_column=Column(String(36), nullable=False))
    grant_version: int = Field(sa_column=Column(BigInteger, nullable=False))
    model_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    usage_month: str = Field(sa_column=Column(String(7), nullable=False))
    policy_version: int = Field(sa_column=Column(BigInteger, nullable=False))
    event_version: int = Field(sa_column=Column(BigInteger, nullable=False))
    quota_epoch: int = Field(sa_column=Column(BigInteger, nullable=False))
    input_tokens: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    output_tokens: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    total_tokens: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    status: str = Field(
        default="RUNNING", sa_column=Column(String(24), nullable=False, server_default=text("'RUNNING'"))
    )
    usage_source: str | None = Field(default=None, sa_column=Column(String(24), nullable=True))
    started_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    ended_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    settled_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    provider_request_id: str | None = Field(default=None, sa_column=Column(String(256), nullable=True))
    trace_id: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    error_code: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    latency_ms: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    reconciliation_operation_id: str | None = Field(default=None, sa_column=Column(String(36), nullable=True))
