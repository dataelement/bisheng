from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, String, Text, UniqueConstraint, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT


class KnowledgeSpaceFileChangeExecutionStepState:
    PENDING = "pending"
    DISPATCHED = "dispatched"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    COMPENSATING = "compensating"
    COMPENSATED = "compensated"


class KnowledgeSpaceFileChangeExecutionStepBase(SQLModelSerializable):
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, nullable=False, server_default=text("1")),
    )
    request_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    step_code: str = Field(sa_column=Column(String(64), nullable=False))
    attempt_token: str = Field(sa_column=Column(String(64), nullable=False))
    idempotency_key: str = Field(sa_column=Column(String(192), nullable=False))
    state: str = Field(
        default=KnowledgeSpaceFileChangeExecutionStepState.PENDING,
        sa_column=Column(String(32), nullable=False, server_default=text("'pending'")),
    )
    attempt_count: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text("0")),
    )
    next_retry_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    task_id: str | None = Field(default=None, sa_column=Column(String(255), nullable=True))
    result_digest: str | None = Field(default=None, sa_column=Column(String(255), nullable=True))
    error_summary: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT),
    )
    acked_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))


class KnowledgeSpaceFileChangeExecutionStep(
    KnowledgeSpaceFileChangeExecutionStepBase,
    table=True,
):
    __tablename__ = "knowledge_space_file_change_execution_step"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "request_id",
            "step_code",
            name="uq_ks_change_step",
        ),
        Index(
            "idx_ks_change_step_retry",
            "tenant_id",
            "state",
            "next_retry_at",
            "id",
        ),
    )

    id: int | None = Field(
        default=None,
        sa_column=Column(
            BigInteger().with_variant(Integer, "sqlite"),
            primary_key=True,
            autoincrement=True,
        ),
    )
