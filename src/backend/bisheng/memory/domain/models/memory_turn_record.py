"""memory_turn_record: memory events of one conversation turn (decision 15)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import JsonType

KIND_SUMMARY = "summary"
KIND_WRITE = "write"
KIND_RETRIEVED = "retrieved"


class MemoryTurnRecord(SQLModelSerializable, table=True):
    __tablename__ = "memory_turn_record"
    __table_args__ = (
        Index("idx_memory_turn_message", "message_id"),
        Index("idx_memory_turn_turn", "turn_id"),
        Index("idx_memory_turn_user", "tenant_id", "user_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    turn_id: str = Field(sa_column=Column(String(64), nullable=False))
    chat_id: Optional[str] = Field(default=None, sa_column=Column(String(64), nullable=True))
    message_id: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True))
    tenant_id: int = Field(sa_column=Column(Integer, nullable=False))
    user_id: int = Field(sa_column=Column(Integer, nullable=False))
    kind: str = Field(sa_column=Column(String(16), nullable=False))
    op: Optional[str] = Field(default=None, sa_column=Column(String(16), nullable=True))
    item_id: Optional[str] = Field(default=None, sa_column=Column(String(36), nullable=True))
    related_item_id: Optional[str] = Field(default=None, sa_column=Column(String(36), nullable=True))
    item_ids: Optional[list] = Field(default=None, sa_column=Column(JsonType, nullable=True))
    resident_rev: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True))
    resident_day: Optional[str] = Field(default=None, sa_column=Column(String(10), nullable=True))
    scene_class: Optional[str] = Field(default=None, sa_column=Column(String(16), nullable=True))
    undone: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, server_default=text("0")))
    consolidated: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, server_default=text("0")))
    ended: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, server_default=text("0")))
    create_time: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    )
