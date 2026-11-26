"""memory_user_setting: per-user switch, timezone and content revision (decisions 8, 13, 17)."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Boolean, Column, Integer, String, UniqueConstraint, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable


class MemoryUserSetting(SQLModelSerializable, table=True):
    __tablename__ = "memory_user_setting"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", name="uq_memory_user_setting"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    tenant_id: int = Field(sa_column=Column(Integer, nullable=False))
    user_id: int = Field(sa_column=Column(Integer, nullable=False))
    enabled: bool = Field(default=True, sa_column=Column(Boolean, nullable=False, server_default=text("1")))
    timezone: Optional[str] = Field(default=None, sa_column=Column(String(64), nullable=True))
    rev: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
