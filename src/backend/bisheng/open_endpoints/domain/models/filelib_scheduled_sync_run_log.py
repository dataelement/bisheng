from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, String, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable

AUTOMOTIVE_SHEET_INTRO_JOB_CODE = "automotive_sheet_intro"


class FilelibScheduledSyncRunLog(SQLModelSerializable, table=True):
    __tablename__ = "filelib_scheduled_sync_run_log"

    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, nullable=False, server_default=text("1"), comment="Tenant ID"),
    )
    job_code: str = Field(sa_column=Column(String(64), nullable=False))
    trigger_type: str = Field(sa_column=Column(String(16), nullable=False))
    status: str = Field(
        default="running",
        sa_column=Column(String(16), nullable=False, server_default=text("'running'")),
    )
    developer_token_id: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))
    file_id: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))
    knowledge_id: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))
    file_name: str | None = Field(default=None, sa_column=Column(String(200), nullable=True))
    error_message: str | None = Field(default=None, sa_column=Column(String(500), nullable=True))
    start_time: datetime = Field(sa_column=Column(DateTime, nullable=False))
    end_time: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    duration_ms: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )

    __table_args__ = (Index("ix_fssrl_tenant_job_id", "tenant_id", "job_code", "id"),)
