"""平台 Agent 的受理快照与调用许可。由 Workflow 领域维护。"""

from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Index
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import JsonType


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class PlatformAgentExecution(SQLModelSerializable, table=True):
    __tablename__ = "workflow_platform_agent_execution"
    __table_args__ = (Index("ix_pa_execution_session", "workflow_id", "session_id", "create_time"),)

    execution_id: str = Field(primary_key=True, max_length=32)
    tenant_id: int = Field(index=True)
    workflow_id: str = Field(index=True, max_length=32)
    session_id: str = Field(max_length=128)
    user_id: int = Field(index=True)
    entry_kind: str = Field(max_length=24)
    provider_mode: str = Field(max_length=16)
    connection_id: str = Field(max_length=128)
    policy_revision: str = Field(max_length=128)
    graph_digest: str = Field(max_length=64)
    graph_snapshot: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    actor_reference: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    dispatches: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    calls: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    state: str = Field(default="READY", max_length=16)
    stop_requested: bool = Field(default=False)
    create_time: datetime = Field(default_factory=utc_now, sa_column=Column(DateTime, nullable=False))
    update_time: datetime = Field(default_factory=utc_now, sa_column=Column(DateTime, nullable=False))
