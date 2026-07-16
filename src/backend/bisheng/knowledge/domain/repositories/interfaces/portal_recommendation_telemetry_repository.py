from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from bisheng.knowledge.domain.services.portal_recommendation_pool_service import PortalRecommendationView


@dataclass(frozen=True, slots=True)
class PortalSearchQuerySignal:
    query: str
    last_searched_at: datetime
    count: int


@dataclass(frozen=True, slots=True)
class PortalInterestHit:
    space_id: int
    file_id: int
    # query -> (title match score, tag match score, summary match score)
    query_field_scores: Mapping[str, tuple[float, float, float]]


class PortalRecommendationTelemetryRepository(ABC):
    @abstractmethod
    async def list_recent_search_queries(
        self,
        tenant_id: int,
        user_id: int,
        since: datetime,
        limit: int,
    ) -> list[PortalSearchQuerySignal]: ...

    @abstractmethod
    async def search_interest_candidates(
        self,
        tenant_id: int,
        queries: Sequence[PortalSearchQuerySignal],
        limit: int,
    ) -> list[PortalInterestHit]: ...

    @abstractmethod
    async def delete_expired_searches(self, tenant_id: int, before: datetime) -> int: ...

    @abstractmethod
    async def list_recent_document_views(
        self,
        tenant_id: int,
        since: datetime,
        before: datetime,
        limit: int | None,
    ) -> list[PortalRecommendationView]: ...
