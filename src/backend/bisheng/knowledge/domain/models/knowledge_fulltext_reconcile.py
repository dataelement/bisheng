"""全文对账轮次与文件级问题; 不持久化正文。"""

from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, String
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import JsonType


class FulltextReconcileRun(SQLModelSerializable, table=True):
    __tablename__ = "knowledge_fulltext_reconcile_run"
    id: str = Field(sa_column=Column(String(32), primary_key=True))
    day: str = Field(sa_column=Column(String(10), nullable=False, index=True))
    status: str = Field(default="scanning", sa_column=Column(String(32), nullable=False))
    phase: str = Field(default="forward", sa_column=Column(String(16), nullable=False))
    cursor: int = Field(default=0, sa_column=Column(BigInteger, nullable=False))
    upper_id: int = Field(default=0, sa_column=Column(BigInteger, nullable=False))
    counters: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    started_at: datetime = Field(sa_column=Column(DateTime, nullable=False))
    updated_at: datetime = Field(sa_column=Column(DateTime, nullable=False))


class FulltextReconcileIssue(SQLModelSerializable, table=True):
    __tablename__ = "knowledge_fulltext_reconcile_issue"
    __table_args__ = (Index("ix_kfri_due", "run_id", "status", "next_retry_at"),)
    run_id: str = Field(sa_column=Column(String(32), primary_key=True))
    file_id: int = Field(sa_column=Column(BigInteger, primary_key=True))
    status: str = Field(default="pending", sa_column=Column(String(24), nullable=False))
    reason: str = Field(default="", sa_column=Column(String(128), nullable=False))
    attempts: int = Field(default=0, sa_column=Column(Integer, nullable=False))
    next_retry_at: datetime | None = Field(default=None, sa_column=Column(DateTime))
    fingerprint: str | None = Field(default=None, sa_column=Column(String(64)))
    task_id: str | None = Field(default=None, sa_column=Column(String(64)))
    updated_at: datetime = Field(sa_column=Column(DateTime, nullable=False))
