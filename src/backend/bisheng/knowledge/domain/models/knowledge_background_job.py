"""知识库发布和清理的持久化意图及逐项执行进度。"""

from datetime import datetime

from sqlalchemy import Column, Index, String
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import JsonType


class KnowledgeBackgroundJob(SQLModelSerializable, table=True):
    __tablename__ = "knowledge_background_job"
    __table_args__ = (Index("ix_kbj_due", "status", "next_retry_at", "lease_until"),)
    id: str = Field(sa_column=Column(String(64), primary_key=True))
    tenant_id: int = Field(index=True)
    kind: str = Field(sa_column=Column(String(32), nullable=False))
    parent_id: str | None = Field(default=None, index=True, max_length=64)
    payload: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    status: str = Field(default="pending", max_length=16)
    attempts: int = Field(default=0)
    lease_owner: str | None = Field(default=None, max_length=64)
    lease_until: datetime | None = Field(default=None)
    next_retry_at: datetime | None = Field(default=None)
    last_error: str | None = Field(default=None, max_length=1000)
    create_time: datetime = Field(default_factory=datetime.now)
    update_time: datetime = Field(default_factory=datetime.now)
