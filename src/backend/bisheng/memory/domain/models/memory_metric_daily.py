"""memory_metric_daily: daily counters flushed from Redis (decision 20). Never holds content."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Column, Integer, String, UniqueConstraint
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable


class MemoryMetricDaily(SQLModelSerializable, table=True):
    __tablename__ = "memory_metric_daily"
    __table_args__ = (
        UniqueConstraint("day", "tenant_id", "scene", "app_id", "metric", name="uq_memory_metric_daily"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    day: str = Field(sa_column=Column(String(10), nullable=False))
    tenant_id: int = Field(sa_column=Column(Integer, nullable=False))
    scene: str = Field(default="", sa_column=Column(String(16), nullable=False))
    app_id: str = Field(default="", sa_column=Column(String(64), nullable=False))
    metric: str = Field(sa_column=Column(String(64), nullable=False))
    value: int = Field(default=0, sa_column=Column(Integer, nullable=False))
