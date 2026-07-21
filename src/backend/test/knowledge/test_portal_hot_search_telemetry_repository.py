from datetime import datetime, timezone

import pytest

from bisheng.core.context.tenant import set_current_tenant_id
from bisheng.knowledge.domain.repositories.implementations.portal_hot_search_telemetry_repository_impl import (
    PortalHotSearchTelemetryRepositoryImpl,
)

_SINCE = datetime(2026, 6, 16, tzinfo=timezone.utc)
_BEFORE = datetime(2026, 7, 16, tzinfo=timezone.utc)


class _FakeES:
    def __init__(self, responses):
        self._responses = list(responses)
        self.bodies = []

    async def search(self, index, body):
        self.bodies.append(body)
        return self._responses.pop(0)


def _agg_response(buckets, after_key=None):
    return {"aggregations": {"queries": {"buckets": buckets, "after_key": after_key}}}


def _bucket(query, doc_count, users):
    return {"key": {"query": query}, "doc_count": doc_count, "users": {"value": users}}


@pytest.fixture(autouse=True)
def _tenant():
    set_current_tenant_id(1)
    yield
    set_current_tenant_id(None)


async def test_aggregate_builds_manual_filter_and_sorts_candidates():
    es = _FakeES([_agg_response([_bucket("b", 5, 2), _bucket("a", 20, 8)], after_key=None)])
    repo = PortalHotSearchTelemetryRepositoryImpl(es_client=es)

    result = await repo.aggregate_candidate_queries(
        1, _SINCE, _BEFORE, page_size=1000, max_pages=10, candidate_top_n=100
    )

    assert [s.normalized_query for s in result.stats] == ["a", "b"]  # sorted by doc_count desc
    assert result.stats[0].approx_users == 8
    assert result.es_pages == 1
    assert result.truncated is False

    # manual filter: portal_search + search_page-or-missing entry_point, excludes home_hot_keyword
    filters = es.bodies[0]["query"]["bool"]["filter"]
    assert {"term": {"event_type": "portal_search"}} in filters
    entry_clause = next(f for f in filters if "bool" in f and "should" in f["bool"])
    should = entry_clause["bool"]["should"]
    assert {"term": {"event_data.entry_point": "search_page"}} in should
    assert any("must_not" in s.get("bool", {}) for s in should)
    ts_range = next(f for f in filters if "range" in f)["range"]["timestamp"]
    assert ts_range == {
        "gte": int(_SINCE.timestamp() * 1000),
        "lt": int(_BEFORE.timestamp() * 1000),
    }


async def test_aggregate_truncates_when_candidate_cap_exceeded():
    buckets = [_bucket(f"q{i}", 100 - i, 3) for i in range(5)]
    es = _FakeES([_agg_response(buckets, after_key=None)])
    repo = PortalHotSearchTelemetryRepositoryImpl(es_client=es)

    result = await repo.aggregate_candidate_queries(1, _SINCE, _BEFORE, page_size=1000, max_pages=10, candidate_top_n=3)
    assert len(result.stats) == 3
    assert result.truncated is True


async def test_aggregate_marks_truncated_when_page_cap_reached():
    # always returns an after_key so pagination never naturally stops
    responses = [_agg_response([_bucket("q", 1, 1)], after_key={"query": "q"}) for _ in range(3)]
    es = _FakeES(responses)
    repo = PortalHotSearchTelemetryRepositoryImpl(es_client=es)

    result = await repo.aggregate_candidate_queries(
        1, _SINCE, _BEFORE, page_size=1000, max_pages=3, candidate_top_n=100
    )
    assert result.es_pages == 3
    assert result.truncated is True


async def test_list_candidate_records_maps_hits():
    ts = (datetime(2026, 7, 10, tzinfo=timezone.utc)).timestamp()
    hits_page = {
        "hits": {
            "hits": [
                {
                    "_source": {
                        "timestamp": ts,
                        "user_context": {"user_id": 42},
                        "event_data": {"query": "设备检修安全要求", "normalized_query": "设备检修安全要求"},
                    },
                    "sort": [ts, "e1"],
                }
            ]
        }
    }
    es = _FakeES([hits_page])
    repo = PortalHotSearchTelemetryRepositoryImpl(es_client=es)

    result = await repo.list_candidate_search_records(
        1, ["设备检修安全要求"], _SINCE, _BEFORE, page_size=1000, max_pages=10, per_query_scan_cap=50000
    )
    assert len(result.records) == 1
    assert result.records[0].user_id == 42
    assert result.records[0].normalized_query == "设备检修安全要求"
    # candidate terms filter applied
    filters = es.bodies[0]["query"]["bool"]["filter"]
    assert {"terms": {"event_data.normalized_query.keyword": ["设备检修安全要求"]}} in filters


async def test_list_candidate_records_empty_when_no_candidates():
    es = _FakeES([])
    repo = PortalHotSearchTelemetryRepositoryImpl(es_client=es)
    result = await repo.list_candidate_search_records(
        1, [], _SINCE, _BEFORE, page_size=1000, max_pages=10, per_query_scan_cap=50000
    )
    assert result.records == []
    assert result.es_pages == 0
