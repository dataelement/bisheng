"""memory_resident_snapshot: which resident items were injected for a rev and day (decision 8)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import JsonType


class MemoryResidentSnapshot(SQLModelSerializable, table=True):
    __tablename__ = "memory_resident_snapshot"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "rev", "day", "scene_class", name="uq_memory_resident_snapshot"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    tenant_id: int = Field(sa_column=Column(Integer, nullable=False))
    user_id: int = Field(sa_column=Column(Integer, nullable=False))
    rev: int = Field(sa_column=Column(Integer, nullable=False))
    day: str = Field(sa_column=Column(String(10), nullable=False))
    scene_class: str = Field(sa_column=Column(String(16), nullable=False))
    item_ids: list = Field(default_factory=list, sa_column=Column(JsonType, nullable=False))
    create_time: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    )
