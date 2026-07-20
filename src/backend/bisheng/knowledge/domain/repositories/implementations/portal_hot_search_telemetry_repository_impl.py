"""ES implementation of the hot-search telemetry reader (F048).

Reads manual ``portal_search`` events from the statistics ES instance using a
two-pass strategy so large tenants never load 30 days of raw events into
memory:

- Pass1: composite terms aggregation on ``normalized_query`` (+ cardinality of
  users) to pick candidate Top-N.
- Pass2: ``search_after`` scan of raw ``(user_id, timestamp)`` rows for the
  candidate queries only, bounded by hard caps.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

from elasticsearch import AsyncElasticsearch

from bisheng.common.services.telemetry.telemetry_service import telemetry_service
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.search.elasticsearch.manager import get_statistics_es_connection
from bisheng.knowledge.domain.repositories.interfaces.portal_hot_search_telemetry_repository import (
    CandidateAggregateResult,
    PortalHotSearchTelemetryRepository,
    SearchRecordsResult,
)
from bisheng.knowledge.domain.schemas.portal_hot_search_schema import (
    CandidateQueryStat,
    PortalSearchRecord,
)


class PortalHotSearchTelemetryRepositoryImpl(PortalHotSearchTelemetryRepository):
    NORMALIZED_QUERY_FIELD = "event_data.normalized_query.keyword"
    ENTRY_POINT_FIELD = "event_data.entry_point"

    def __init__(self, *, es_client: AsyncElasticsearch | None = None) -> None:
        self._es_client = es_client

    @staticmethod
    def _epoch_ms(value: datetime) -> int:
        """Convert UTC datetime to ES range bounds.

        ``base_telemetry_events`` stores ``timestamp`` as epoch milliseconds in
        practice (despite mapping ``epoch_second`` on legacy indices). Range
        filters must use ms or Pass1/Pass2 return zero hits.
        """
        return int(value.timestamp() * 1000)

    @staticmethod
    def _assert_current_tenant(tenant_id: int) -> None:
        current = get_current_tenant_id()
        if current is None or int(current) != int(tenant_id):
            raise PermissionError("hot-search telemetry tenant does not match current context")

    async def _client(self) -> AsyncElasticsearch:
        if self._es_client is None:
            self._es_client = await get_statistics_es_connection()
        return self._es_client

    def _manual_filter(self, tenant_id: int, since: datetime, before: datetime) -> list[dict]:
        # Manual = entry_point search_page OR entry_point missing (legacy data);
        # this excludes home_hot_keyword.
        return [
            {"term": {"tenant_id": tenant_id}},
            {"term": {"event_type": "portal_search"}},
            {
                "range": {
                    "timestamp": {
                        "gte": PortalHotSearchTelemetryRepositoryImpl._epoch_ms(since),
                        "lt": PortalHotSearchTelemetryRepositoryImpl._epoch_ms(before),
                    }
                }
            },
            {
                "bool": {
                    "should": [
                        {"term": {self.ENTRY_POINT_FIELD: "search_page"}},
                        {"bool": {"must_not": {"exists": {"field": self.ENTRY_POINT_FIELD}}}},
                    ],
                    "minimum_should_match": 1,
                }
            },
        ]

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
        self._assert_current_tenant(tenant_id)
        since = since.astimezone(timezone.utc)
        before = before.astimezone(timezone.utc)
        client = await self._client()
        filters = self._manual_filter(tenant_id, since, before)

        totals: dict[str, int] = {}
        approx_users: dict[str, int] = {}
        after_key: dict | None = None
        pages = 0
        truncated = False
        page_size = max(int(page_size), 1)
        while pages < max_pages:
            composite: dict = {
                "size": page_size,
                "sources": [{"query": {"terms": {"field": self.NORMALIZED_QUERY_FIELD}}}],
            }
            if after_key is not None:
                composite["after"] = after_key
            body = {
                "size": 0,
                "query": {"bool": {"filter": filters}},
                "aggs": {
                    "queries": {
                        "composite": composite,
                        "aggregations": {"users": {"cardinality": {"field": "user_context.user_id"}}},
                    }
                },
            }
            response = await client.search(index=telemetry_service.index_name, body=body)
            pages += 1
            agg = (response.get("aggregations") or {}).get("queries") or {}
            buckets = agg.get("buckets") or []
            for bucket in buckets:
                query = str((bucket.get("key") or {}).get("query") or "").strip()
                if not query:
                    continue
                totals[query] = totals.get(query, 0) + int(bucket.get("doc_count") or 0)
                approx_users[query] = max(
                    approx_users.get(query, 0),
                    int((bucket.get("users") or {}).get("value") or 0),
                )
            after_key = agg.get("after_key")
            if not after_key or not buckets:
                break
        else:
            truncated = True

        stats = [
            CandidateQueryStat(normalized_query=query, doc_count=count, approx_users=approx_users.get(query, 0))
            for query, count in totals.items()
        ]
        stats.sort(key=lambda s: (-s.doc_count, s.normalized_query))
        if len(stats) > candidate_top_n:
            stats = stats[:candidate_top_n]
            truncated = True
        return CandidateAggregateResult(stats=stats, es_pages=pages, truncated=truncated)

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
        self._assert_current_tenant(tenant_id)
        candidates = [q for q in dict.fromkeys(normalized_queries) if q]
        if not candidates:
            return SearchRecordsResult(records=[], es_pages=0, truncated=False)
        since = since.astimezone(timezone.utc)
        before = before.astimezone(timezone.utc)
        client = await self._client()
        filters = self._manual_filter(tenant_id, since, before)
        filters = [*filters, {"terms": {self.NORMALIZED_QUERY_FIELD: candidates}}]

        records: list[PortalSearchRecord] = []
        search_after = None
        pages = 0
        truncated = False
        page_size = max(int(page_size), 1)
        while pages < max_pages and len(records) < per_query_scan_cap:
            body = {
                "size": min(page_size, per_query_scan_cap - len(records)),
                "track_total_hits": False,
                "query": {"bool": {"filter": filters}},
                "sort": [{"timestamp": "asc"}, {"event_id": "asc"}],
                "_source": ["timestamp", "user_context.user_id", "event_data"],
            }
            if search_after is not None:
                body["search_after"] = search_after
            response = await client.search(index=telemetry_service.index_name, body=body)
            pages += 1
            hits = ((response.get("hits") or {}).get("hits")) or []
            for hit in hits:
                source = hit.get("_source") or {}
                event_data = source.get("event_data") or {}
                user_id = (source.get("user_context") or {}).get("user_id")
                timestamp = source.get("timestamp")
                if not str(user_id or "").isdigit() or timestamp is None:
                    continue
                try:
                    searched_at = datetime.fromtimestamp(float(timestamp), tz=timezone.utc)
                except (TypeError, ValueError, OSError):
                    continue
                records.append(
                    PortalSearchRecord(
                        user_id=int(user_id),
                        query=str(event_data.get("query") or event_data.get("normalized_query") or ""),
                        normalized_query=str(event_data.get("normalized_query") or ""),
                        searched_at=searched_at,
                    )
                )
            if len(hits) < body["size"]:
                break
            search_after = hits[-1].get("sort")
            if not search_after:
                break
        else:
            truncated = True

        return SearchRecordsResult(records=records, es_pages=pages, truncated=truncated)
