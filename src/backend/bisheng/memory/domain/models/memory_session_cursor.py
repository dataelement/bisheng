"""memory_session_cursor: eligibility registration + consolidation watermark (decisions 6, 7)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable

STATE_IDLE = "idle"
STATE_PENDING = "pending"
STATE_RUNNING = "running"


class MemorySessionCursor(SQLModelSerializable, table=True):
    __tablename__ = "memory_session_cursor"
    __table_args__ = (
        Index("idx_memory_cursor_due", "state", "next_run_at", "last_activity_at"),
        Index("idx_memory_cursor_user", "tenant_id", "user_id"),
    )

    chat_id: str = Field(sa_column=Column(String(64), primary_key=True))
    tenant_id: int = Field(sa_column=Column(Integer, nullable=False))
    user_id: int = Field(sa_column=Column(Integer, nullable=False))
    eligible: bool = Field(default=True, sa_column=Column(Boolean, nullable=False, server_default=text("1")))
    timezone: Optional[str] = Field(default=None, sa_column=Column(String(64), nullable=True))
    last_activity_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    last_message_id: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    watermark_message_id: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    state: str = Field(default=STATE_IDLE, sa_column=Column(String(16), nullable=False, server_default=STATE_IDLE))
    locked_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    fail_count: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    next_run_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    create_time: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    )
