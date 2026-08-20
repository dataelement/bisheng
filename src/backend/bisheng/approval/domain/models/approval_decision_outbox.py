from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Index, Integer, String, Text, UniqueConstraint, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT


class ApprovalDecisionOutboxStatus:
    PENDING = "pending"
    PROCESSING = "processing"
    DELIVERED = "delivered"
    FAILED = "failed"


class ApprovalDecisionFailureKind:
    RETRYABLE = "retryable"
    PERMANENT = "permanent"


class ApprovalDecisionOutboxBase(SQLModelSerializable):
    tenant_id: int | None = Field(default=None, sa_column=Column(Integer, nullable=False, index=True))
    instance_id: int = Field(sa_column=Column(Integer, nullable=False, index=True))
    scenario_code: str = Field(sa_column=Column(String(64), nullable=False))
    subscriber_key: str = Field(sa_column=Column(String(128), nullable=False))
    business_request_type: str = Field(sa_column=Column(String(64), nullable=False))
    business_request_id: str = Field(sa_column=Column(String(128), nullable=False))
    business_key: str = Field(sa_column=Column(String(255), nullable=False))
    request_fingerprint: str = Field(sa_column=Column(String(128), nullable=False))
    decision: str = Field(sa_column=Column(String(32), nullable=False))
    decision_version: int = Field(
        default=1,
        sa_column=Column(Integer, nullable=False, server_default=text("1")),
    )
    event_version: int = Field(
        default=1,
        sa_column=Column(Integer, nullable=False, server_default=text("1")),
    )
    decided_at: datetime = Field(sa_column=Column(DateTime, nullable=False))
    operator_user_id: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))
    status: str = Field(
        default=ApprovalDecisionOutboxStatus.PENDING,
        sa_column=Column(String(32), nullable=False, server_default=text("'pending'")),
    )
    claim_token: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    claimed_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    claim_deadline: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    retry_count: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text("0")),
    )
    error_summary: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    next_retry_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    failure_kind: str | None = Field(default=None, sa_column=Column(String(32), nullable=True))
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT),
    )


class ApprovalDecisionOutbox(ApprovalDecisionOutboxBase, table=True):
    __tablename__ = "approval_decision_outbox"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "instance_id",
            "decision_version",
            name="uq_approval_decision_outbox_instance_version",
        ),
        Index(
            "idx_approval_decision_outbox_retry",
            "tenant_id",
            "status",
            "next_retry_at",
            "id",
        ),
        Index(
            "idx_approval_decision_outbox_lease",
            "tenant_id",
            "status",
            "claim_deadline",
            "id",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
