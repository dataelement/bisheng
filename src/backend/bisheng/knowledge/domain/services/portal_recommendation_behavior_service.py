from __future__ import annotations

import inspect
import math
import re
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from bisheng.knowledge.domain.repositories.interfaces.portal_recommendation_telemetry_repository import (
    PortalRecommendationTelemetryRepository,
    PortalSearchQuerySignal,
)

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_search_query(query: str) -> str:
    return _WHITESPACE_RE.sub(" ", query.strip()).casefold()


class PortalRecommendationBehaviorStateRepository(Protocol):
    async def increment_behavior_version(self, tenant_id: int, user_id: int) -> int: ...

    async def record_read(
        self,
        tenant_id: int,
        user_id: int,
        space_id: int,
        file_id: int,
        read_at: datetime,
    ) -> None: ...

    async def record_read_and_increment_behavior_version(
        self,
        tenant_id: int,
        user_id: int,
        space_id: int,
        file_id: int,
        read_at: datetime,
    ) -> int: ...

    async def replace_interest(
        self,
        tenant_id: int,
        user_id: int,
        entries: Sequence[tuple[str, float]],
        ttl_seconds: int,
    ) -> None: ...


InterestRebuildEnqueuer = Callable[..., Any]


class PortalRecommendationBehaviorService:
    INTEREST_TTL_SECONDS = 30 * 60

    def __init__(
        self,
        *,
        state_repository: PortalRecommendationBehaviorStateRepository,
        telemetry_repository: PortalRecommendationTelemetryRepository | None,
        enqueue_interest_rebuild: InterestRebuildEnqueuer | None = None,
    ):
        self.state_repository = state_repository
        self.telemetry_repository = telemetry_repository
        self.enqueue_interest_rebuild = enqueue_interest_rebuild

    async def record_search(
        self,
        *,
        tenant_id: int,
        user_id: int,
        query: str,
        searched_at: datetime | None = None,
    ) -> None:
        searched_at = searched_at or datetime.now(timezone.utc)
        normalized_query = normalize_search_query(query)
        if not normalized_query:
            return
        await self.state_repository.increment_behavior_version(tenant_id, user_id)
        if self.enqueue_interest_rebuild is not None:
            result = self.enqueue_interest_rebuild(
                tenant_id=tenant_id,
                user_id=user_id,
                current_query=normalized_query,
                searched_at=searched_at,
            )
            if inspect.isawaitable(result):
                await result

    async def record_read(
        self,
        *,
        tenant_id: int,
        user_id: int,
        space_id: int,
        file_id: int,
        read_at: datetime | None = None,
    ) -> None:
        read_at = read_at or datetime.now(timezone.utc)
        await self.state_repository.record_read_and_increment_behavior_version(
            tenant_id,
            user_id,
            space_id,
            file_id,
            read_at,
        )

    @staticmethod
    def _query_weight(signal: PortalSearchQuerySignal, now: datetime) -> float:
        age_days = max((now - signal.last_searched_at).total_seconds(), 0) / 86400
        if age_days <= 7:
            recency_weight = 1.0
        elif age_days <= 30:
            recency_weight = 0.7
        else:
            recency_weight = 0.4
        return recency_weight * (1 + 0.2 * math.log(1 + max(signal.count, 1)))

    async def build_interest_top50(
        self,
        *,
        tenant_id: int,
        user_id: int,
        current_query: str | None = None,
        searched_at: datetime | None = None,
        now: datetime | None = None,
    ) -> list[tuple[str, float]]:
        if self.telemetry_repository is None:
            return []
        now = now or datetime.now(timezone.utc)
        searched_at = searched_at or now
        signals = await self.telemetry_repository.list_recent_search_queries(
            tenant_id,
            user_id,
            now - timedelta(days=90),
            20,
        )
        merged: dict[str, PortalSearchQuerySignal] = {}
        for signal in signals:
            normalized = normalize_search_query(signal.query)
            if not normalized:
                continue
            previous = merged.get(normalized)
            if previous is None:
                merged[normalized] = PortalSearchQuerySignal(normalized, signal.last_searched_at, signal.count)
            else:
                merged[normalized] = PortalSearchQuerySignal(
                    normalized,
                    max(previous.last_searched_at, signal.last_searched_at),
                    previous.count + signal.count,
                )
        normalized_current = normalize_search_query(current_query or "")
        if normalized_current:
            previous = merged.get(normalized_current)
            merged[normalized_current] = PortalSearchQuerySignal(
                normalized_current,
                max(previous.last_searched_at, searched_at) if previous else searched_at,
                (previous.count if previous else 0) + 1,
            )

        query_signals = sorted(merged.values(), key=lambda item: item.last_searched_at, reverse=True)[:20]
        if not query_signals:
            await self.state_repository.replace_interest(tenant_id, user_id, [], self.INTEREST_TTL_SECONDS)
            return []
        query_weights = {signal.query: self._query_weight(signal, now) for signal in query_signals}
        hits = await self.telemetry_repository.search_interest_candidates(tenant_id, query_signals, 50)

        entries: list[tuple[str, float]] = []
        for hit in hits:
            score = 0.0
            for query, field_scores in hit.query_field_scores.items():
                normalized = normalize_search_query(query)
                query_weight = query_weights.get(normalized)
                if query_weight is None:
                    continue
                title_score, tag_score, summary_score = field_scores
                score += query_weight * (4 * title_score + 3 * tag_score + summary_score)
            if score > 0:
                entries.append((f"{hit.space_id}:{hit.file_id}", score))
        entries.sort(key=lambda item: (-item[1], item[0]))
        entries = entries[:50]
        await self.state_repository.replace_interest(
            tenant_id,
            user_id,
            entries,
            self.INTEREST_TTL_SECONDS,
        )
        return entries
