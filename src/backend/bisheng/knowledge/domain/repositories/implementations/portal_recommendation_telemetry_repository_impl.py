from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime, timezone

from elasticsearch import AsyncElasticsearch
from loguru import logger

from bisheng.common.services.telemetry.telemetry_service import telemetry_service
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.search.elasticsearch.manager import get_statistics_es_connection
from bisheng.knowledge.domain.repositories.interfaces.portal_recommendation_telemetry_repository import (
    PortalInterestHit,
    PortalRecommendationTelemetryRepository,
    PortalSearchQuerySignal,
)
from bisheng.knowledge.domain.services.portal_recommendation_pool_service import (
    PortalRecommendationPoolService,
    PortalRecommendationView,
)

InterestSearcher = Callable[
    [int, Sequence[PortalSearchQuerySignal], int],
    Awaitable[list[PortalInterestHit]] | list[PortalInterestHit],
]


class PortalRecommendationTelemetryRepositoryImpl(PortalRecommendationTelemetryRepository):
    NORMALIZED_QUERY_FIELD = "event_data.normalized_query.keyword"
    DOCUMENT_VIEW_PAGE_SIZE = 1_000

    def __init__(
        self,
        *,
        es_client: AsyncElasticsearch | None = None,
        interest_searcher: InterestSearcher | None = None,
    ):
        self._es_client = es_client
        self._interest_searcher = interest_searcher

    @staticmethod
    def _assert_current_tenant(tenant_id: int) -> None:
        current_tenant_id = get_current_tenant_id()
        if current_tenant_id is None or int(current_tenant_id) != int(tenant_id):
            raise PermissionError("recommendation telemetry tenant does not match current context")

    async def _client(self) -> AsyncElasticsearch:
        if self._es_client is None:
            self._es_client = await get_statistics_es_connection()
        return self._es_client

    async def list_recent_search_queries(
        self,
        tenant_id: int,
        user_id: int,
        since: datetime,
        limit: int,
    ) -> list[PortalSearchQuerySignal]:
        self._assert_current_tenant(tenant_id)
        since = since.astimezone(timezone.utc)
        body = {
            "size": 0,
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"tenant_id": tenant_id}},
                        {"term": {"user_context.user_id": user_id}},
                        {"term": {"event_type": "portal_search"}},
                        {"range": {"timestamp": {"gte": int(since.timestamp())}}},
                    ]
                }
            },
            "aggs": {
                "queries": {
                    "terms": {
                        "field": self.NORMALIZED_QUERY_FIELD,
                        "size": min(max(limit, 1), 20),
                        "order": {"last_seen": "desc"},
                    },
                    "aggs": {"last_seen": {"max": {"field": "timestamp"}}},
                }
            },
        }
        response = await (await self._client()).search(index=telemetry_service.index_name, body=body)
        signals: list[PortalSearchQuerySignal] = []
        for bucket in response.get("aggregations", {}).get("queries", {}).get("buckets", []):
            query = str(bucket.get("key") or "").strip()
            last_seen_ms = bucket.get("last_seen", {}).get("value")
            if not query or last_seen_ms is None:
                continue
            signals.append(
                PortalSearchQuerySignal(
                    query=query,
                    last_searched_at=datetime.fromtimestamp(float(last_seen_ms) / 1000, tz=timezone.utc),
                    count=max(int(bucket.get("doc_count") or 0), 1),
                )
            )
        return signals[:limit]

    async def search_interest_candidates(
        self,
        tenant_id: int,
        queries: Sequence[PortalSearchQuerySignal],
        limit: int,
    ) -> list[PortalInterestHit]:
        self._assert_current_tenant(tenant_id)
        if not queries:
            return []
        searcher = self._interest_searcher
        if searcher is None:
            from bisheng.knowledge.domain.services.portal_recommendation_interest_searcher import (
                PortalRecommendationContentSearcher,
            )

            searcher = PortalRecommendationContentSearcher().search
        result = searcher(tenant_id, queries, min(max(limit, 1), 50))
        return await result if inspect.isawaitable(result) else result

    async def delete_expired_searches(self, tenant_id: int, before: datetime) -> int:
        self._assert_current_tenant(tenant_id)
        before = before.astimezone(timezone.utc)
        body = {
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"tenant_id": tenant_id}},
                        {"term": {"event_type": "portal_search"}},
                        {"range": {"timestamp": {"lt": int(before.timestamp())}}},
                    ]
                }
            }
        }
        response = await (await self._client()).delete_by_query(
            index=telemetry_service.index_name,
            body=body,
            conflicts="proceed",
            refresh=False,
        )
        return int(response.get("deleted") or 0)

    async def list_recent_document_views(
        self,
        tenant_id: int,
        since: datetime,
        before: datetime,
        limit: int | None,
    ) -> list[PortalRecommendationView]:
        self._assert_current_tenant(tenant_id)
        since = since.astimezone(timezone.utc)
        before = before.astimezone(timezone.utc)
        if before < since:
            return []
        hard_limit = max(int(limit), 1) if limit is not None else None
        client = await self._client()
        unique_views: dict[tuple[int, int, object], PortalRecommendationView] = {}
        search_after = None
        while hard_limit is None or len(unique_views) < hard_limit:
            remaining = (
                hard_limit - len(unique_views)
                if hard_limit is not None
                else self.DOCUMENT_VIEW_PAGE_SIZE
            )
            page_size = min(self.DOCUMENT_VIEW_PAGE_SIZE, remaining)
            body = {
                "size": page_size,
                "track_total_hits": False,
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"tenant_id": tenant_id}},
                            {"term": {"event_type": "portal_document_read"}},
                            {
                                "range": {
                                    "timestamp": {
                                        "gte": int(since.timestamp()),
                                        "lte": int(before.timestamp()),
                                    }
                                }
                            },
                        ]
                    }
                },
                "sort": [{"timestamp": "asc"}, {"event_id": "asc"}],
                "_source": ["timestamp", "user_context.user_id", "event_data"],
            }
            if search_after is not None:
                body["search_after"] = search_after
            response = await client.search(index=telemetry_service.index_name, body=body)
            hits = (response.get("hits") or {}).get("hits", [])
            for hit in hits:
                source = hit.get("_source") or {}
                event_data = source.get("event_data") or {}
                user_id = (source.get("user_context") or {}).get("user_id")
                file_id = event_data.get("portal_document_read_file_id", event_data.get("file_id"))
                entry_point = event_data.get(
                    "portal_document_read_entry_point",
                    event_data.get("entry_point", "unknown"),
                )
                timestamp = source.get("timestamp")
                if not str(user_id or "").isdigit() or not str(file_id or "").isdigit():
                    continue
                try:
                    viewed_at = datetime.fromtimestamp(float(timestamp), tz=timezone.utc)
                except (TypeError, ValueError, OSError):
                    continue
                view = PortalRecommendationView(
                    user_id=int(user_id),
                    file_id=int(file_id),
                    viewed_at=viewed_at,
                    source=str(entry_point or "unknown"),
                )
                key = (
                    view.user_id,
                    view.file_id,
                    PortalRecommendationPoolService.business_date(view.viewed_at),
                )
                previous = unique_views.get(key)
                if previous is None or view.viewed_at > previous.viewed_at:
                    unique_views[key] = view
            if len(hits) < page_size:
                break
            search_after = hits[-1].get("sort")
            if not search_after:
                logger.warning(
                    "portal recommendation heat pagination stopped because ES omitted sort values tenant={}",
                    tenant_id,
                )
                break
            if hard_limit is not None and len(unique_views) >= hard_limit:
                logger.warning(
                    "portal recommendation heat facts reached explicit task cap tenant={} cap={}",
                    tenant_id,
                    hard_limit,
                )
                break
        views = sorted(
            unique_views.values(),
            key=lambda item: (item.viewed_at, item.user_id, item.file_id),
        )
        return views[:hard_limit]
