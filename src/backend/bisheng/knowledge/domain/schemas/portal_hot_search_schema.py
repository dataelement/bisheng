"""DTOs for the portal home hot-search batch pipeline (F048)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from pydantic import BaseModel, Field


@dataclass
class PortalSearchRecord:
    """A single manual portal_search event pulled from ES (Pass2)."""

    user_id: int
    query: str
    normalized_query: str
    searched_at: datetime


@dataclass
class CleanedSearchRecord:
    """A manual search record after text cleaning and user-day dedup."""

    user_id: int
    cleaned_query: str
    searched_at: datetime
    local_date: date


@dataclass
class CandidateQueryStat:
    """Pass1 aggregate for a distinct normalized query."""

    normalized_query: str
    doc_count: int
    approx_users: int


@dataclass
class HotSearchIntentGroup:
    """A group of member queries sharing one search intent."""

    intent_key: str
    canonical_query: str
    member_queries: list[str] = field(default_factory=list)


@dataclass
class HotSearchRankItem:
    """A scored intent candidate; ``final_rank`` set only for published Top-K."""

    intent_key: str
    canonical_query: str
    display_query: str
    heat_score: int
    unique_users: int
    search_count_7d: int
    search_count_8_30d: int
    qualified: bool
    final_rank: int | None = None
    rewrite_source: str = "passthrough"
    member_queries: list[str] = field(default_factory=list)


@dataclass
class HotSearchBatchStats:
    """Per-run observability metrics persisted to portal_hot_search_batch_run."""

    batch_id: str
    status: str = "running"
    scanned_count: int = 0
    distinct_query_count: int = 0
    candidate_count: int = 0
    dedup_record_count: int = 0
    qualified_count: int = 0
    llm_group_calls: int = 0
    llm_rewrite_calls: int = 0
    llm_degraded: bool = False
    truncated: bool = False
    es_pages: int = 0
    duration_ms: int = 0
    error_message: str | None = None


class PortalHotSearchItem(BaseModel):
    """Home-facing hot-search entry."""

    rank: int = Field(ge=1, le=50)
    query: str = Field(min_length=1, max_length=100)
