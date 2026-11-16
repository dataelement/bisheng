"""memory_item: one long-term memory item (design §4.2, decisions 2, 4, 8)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, Text, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable

ITEM_TYPES = ("fact", "preference", "experience")
STATUS_ACTIVE = "active"
STATUS_SUPERSEDED = "superseded"
STATUS_DELETED = "deleted"
ORIGIN_EXPLICIT = "explicit"
ORIGIN_AUTO = "auto"
ORIGIN_MANUAL = "manual"
INDEX_OK = "ok"
INDEX_PENDING = "pending"


class MemoryItem(SQLModelSerializable, table=True):
    __tablename__ = "memory_item"
    __table_args__ = (
        Index("idx_memory_item_resident", "tenant_id", "user_id", "status", "pinned", "pin_order"),
        Index("idx_memory_item_type", "tenant_id", "user_id", "status", "type"),
    )

    id: str = Field(sa_column=Column(String(36), primary_key=True))
    tenant_id: int = Field(sa_column=Column(Integer, nullable=False))
    user_id: int = Field(sa_column=Column(Integer, nullable=False))
    scope: str = Field(default="personal", sa_column=Column(String(16), nullable=False, server_default="personal"))
    type: str = Field(sa_column=Column(String(16), nullable=False))
    content: str = Field(sa_column=Column(Text, nullable=False))
    status: str = Field(default=STATUS_ACTIVE, sa_column=Column(String(16), nullable=False))
    superseded_by: Optional[str] = Field(default=None, sa_column=Column(String(36), nullable=True))
    pinned: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, server_default=text("0")))
    pin_order: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    event_time: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    valid_from: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    valid_to: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    recorded_at: datetime = Field(sa_column=Column(DateTime, nullable=False))
    origin: str = Field(sa_column=Column(String(16), nullable=False))
    source_scene: str = Field(sa_column=Column(String(16), nullable=False))
    source_app_id: Optional[str] = Field(default=None, sa_column=Column(String(64), nullable=True))
    source_app_name: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    source_chat_id: Optional[str] = Field(default=None, sa_column=Column(String(64), nullable=True))
    detail_object_key: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    detail_sha256: Optional[str] = Field(default=None, sa_column=Column(String(64), nullable=True))
    index_state: str = Field(default=INDEX_PENDING, sa_column=Column(String(16), nullable=False))
    index_model_id: Optional[str] = Field(default=None, sa_column=Column(String(64), nullable=True))
    rewritten: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, server_default=text("0")))
    last_read_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    detail_read_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    create_time: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    )
