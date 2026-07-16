"""Interface for reading manual portal_search events for hot-search (F048)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from bisheng.knowledge.domain.schemas.portal_hot_search_schema import (
    CandidateQueryStat,
    PortalSearchRecord,
)


@dataclass
class CandidateAggregateResult:
    stats: list[CandidateQueryStat]
    es_pages: int
    truncated: bool


@dataclass
class SearchRecordsResult:
    records: list[PortalSearchRecord]
    es_pages: int
    truncated: bool


class PortalHotSearchTelemetryRepository(ABC):
    """Two-pass ES reader: Pass1 aggregates candidates, Pass2 fetches records."""

    @abstractmethod
    async def aggregate_candidate_queries(
        self,
        tenant_id: int,
        since: datetime,
        before: datetime,
        *,
        page_size: int,
        max_pages: int,
        candidate_top_n: int,
    ) -> CandidateAggregateResult:
        """Pass1: distinct normalized queries with doc_count + approx users."""

    @abstractmethod
    async def list_candidate_search_records(
        self,
        tenant_id: int,
        normalized_queries: Sequence[str],
        since: datetime,
        before: datetime,
        *,
        page_size: int,
        max_pages: int,
        per_query_scan_cap: int,
    ) -> SearchRecordsResult:
        """Pass2: raw (user_id, timestamp) records for the candidate queries."""
