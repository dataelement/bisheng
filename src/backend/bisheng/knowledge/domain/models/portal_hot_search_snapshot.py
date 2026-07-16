"""Portal home hot-search result snapshot and batch diagnostics models.

Three tables owned by this feature:
- ``portal_hot_search_snapshot``: final Top-N ranking consumed by the home page.
- ``portal_hot_search_batch_run``: per-run metadata for observability.
- ``portal_hot_search_candidate``: Top-N candidate diagnostics (incl. non-ranked).
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Index,
    Integer,
    SmallInteger,
    String,
    text,
)
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import LargeText


class PortalHotSearchSnapshot(SQLModelSerializable, table=True):
    __tablename__ = "portal_hot_search_snapshot"

    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, nullable=False, server_default=text("1"), comment="Tenant ID"),
    )
    rank_no: int = Field(sa_column=Column(SmallInteger, nullable=False, comment="Rank 1-5"))
    intent_key: str = Field(sa_column=Column(String(64), nullable=False, comment="Intent group hash"))
    display_query: str = Field(sa_column=Column(String(100), nullable=False, comment="Rewritten question"))
    canonical_query: str = Field(
        sa_column=Column(String(100), nullable=False, comment="Intent representative query"),
    )
    heat_score: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    unique_users: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    search_count_7d: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    search_count_8_30d: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    batch_id: str = Field(sa_column=Column(String(32), nullable=False, comment="{yyyymmdd}-{seq}"))
    computed_at: datetime = Field(sa_column=Column(DateTime, nullable=False))
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )

    __table_args__ = (
        Index("ix_phss_tenant_batch", "tenant_id", "batch_id"),
        Index("ix_phss_tenant_rank", "tenant_id", "rank_no"),
    )


class PortalHotSearchBatchRun(SQLModelSerializable, table=True):
    __tablename__ = "portal_hot_search_batch_run"

    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, nullable=False, server_default=text("1"), comment="Tenant ID"),
    )
    batch_id: str = Field(sa_column=Column(String(32), nullable=False, comment="{yyyymmdd}-{seq}"))
    status: str = Field(
        sa_column=Column(String(16), nullable=False, comment="running/success/failed/degraded"),
    )
    window_start: datetime = Field(sa_column=Column(DateTime, nullable=False))
    window_end: datetime = Field(sa_column=Column(DateTime, nullable=False))
    scanned_count: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    distinct_query_count: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    candidate_count: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    dedup_record_count: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    qualified_count: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    llm_group_calls: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    llm_rewrite_calls: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    llm_degraded: int = Field(default=0, sa_column=Column(SmallInteger, nullable=False, server_default=text("0")))
    truncated: int = Field(default=0, sa_column=Column(SmallInteger, nullable=False, server_default=text("0")))
    duration_ms: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    es_pages: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    error_message: str | None = Field(default=None, sa_column=Column(String(500), nullable=True))
    computed_at: datetime = Field(sa_column=Column(DateTime, nullable=False))
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )

    __table_args__ = (
        Index("ix_phsbr_tenant_time", "tenant_id", "computed_at"),
        Index("ix_phsbr_tenant_batch", "tenant_id", "batch_id"),
    )


class PortalHotSearchCandidate(SQLModelSerializable, table=True):
    __tablename__ = "portal_hot_search_candidate"

    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, nullable=False, server_default=text("1"), comment="Tenant ID"),
    )
    batch_id: str = Field(sa_column=Column(String(32), nullable=False, comment="{yyyymmdd}-{seq}"))
    intent_key: str = Field(sa_column=Column(String(64), nullable=False))
    canonical_query: str = Field(sa_column=Column(String(100), nullable=False))
    display_query: str | None = Field(default=None, sa_column=Column(String(100), nullable=True))
    member_queries: str | None = Field(
        default=None,
        sa_column=Column(LargeText, nullable=True, comment="JSON member queries"),
    )
    heat_score: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    unique_users: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    search_count_7d: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    search_count_8_30d: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    qualified: int = Field(default=0, sa_column=Column(SmallInteger, nullable=False, server_default=text("0")))
    final_rank: int | None = Field(default=None, sa_column=Column(SmallInteger, nullable=True))
    rewrite_source: str | None = Field(
        default=None,
        sa_column=Column(String(16), nullable=True, comment="passthrough/llm/fallback"),
    )
    llm_sample: str | None = Field(
        default=None,
        sa_column=Column(LargeText, nullable=True, comment="Truncated LLM I/O sample"),
    )
    computed_at: datetime = Field(sa_column=Column(DateTime, nullable=False))

    __table_args__ = (Index("ix_phsc_tenant_batch", "tenant_id", "batch_id"),)
