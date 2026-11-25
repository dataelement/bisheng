"""Durable tool call billing ledger projected from Redis usage events."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, Index, String, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import JsonType


class DshToolCall(SQLModelSerializable, table=True):
    """One billed or observed tool call execution with frozen pricing snapshot."""

    __tablename__ = "dsh_tool_call"
    __table_args__ = (
        Index("ix_dsh_tool_call_user_started", "tenant_id", "user_id", "started_at"),
        Index("ix_dsh_tool_call_key_started", "tenant_id", "tool_key", "started_at"),
        CheckConstraint("billed_tokens >= 0", name="ck_dsh_tool_call_billed_tokens"),
        CheckConstraint("cost_micro IS NULL OR cost_micro >= 0", name="ck_dsh_tool_call_cost"),
        CheckConstraint("result IN ('success', 'failed', 'timeout', 'cancelled')", name="ck_dsh_tool_call_result"),
    )
    request_id: str = Field(sa_column=Column(String(36), primary_key=True))
    tenant_id: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=False, index=True))
    user_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    usage_month: str = Field(sa_column=Column(String(7), nullable=False))
    tool_group_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    tool_group_name: str | None = Field(default=None, sa_column=Column(String(256), nullable=True))
    tool_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    tool_key: str = Field(sa_column=Column(String(128), nullable=False))
    engine: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    pricing_snapshot: dict | None = Field(default=None, sa_column=Column(JsonType, nullable=True))
    billed_tokens: int = Field(default=0, sa_column=Column(BigInteger, nullable=False, server_default=text("0")))
    cost_micro: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    currency: str | None = Field(default=None, sa_column=Column(String(3), nullable=True))
    result: str = Field(sa_column=Column(String(16), nullable=False))
    source_type: str | None = Field(default=None, sa_column=Column(String(32), nullable=True))
    source_id: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    started_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    ended_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
