from datetime import datetime, timedelta, timezone

import pytest

from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum
from bisheng.common.schemas.telemetry.base_telemetry_schema import BaseTelemetryEvent, UserContext
from bisheng.common.schemas.telemetry.event_data_schema import PortalSearchEventData
from bisheng.core.context.tenant import current_tenant_id
from bisheng.knowledge.domain.repositories.implementations.portal_recommendation_telemetry_repository_impl import (
    PortalRecommendationTelemetryRepositoryImpl,
)


class _FakeEsClient:
    def __init__(self):
        self.search_calls = []
        self.delete_calls = []

    async def search(self, **kwargs):
        self.search_calls.append(kwargs)
        return {
            "aggregations": {
                "queries": {
                    "buckets": [
                        {
                            "key": "steel",
                            "doc_count": 3,
                            "last_seen": {"value": 1_784_070_400_000},
                        },
                        {
                            "key": "safety",
                            "doc_count": 1,
                            "last_seen": {"value": 1_783_465_200_000},
                        },
                    ]
                }
            }
        }

    async def delete_by_query(self, **kwargs):
        self.delete_calls.append(kwargs)
        return {"deleted": 7}


class _PagedViewsEsClient:
    def __init__(self):
        self.search_calls = []

    async def search(self, **kwargs):
        self.search_calls.append(kwargs)
        page = len(self.search_calls)
        if page == 1:
            hits = [
                {
                    "sort": [1_784_070_400, "a"],
                    "_source": {
                        "timestamp": 1_784_070_400,
                        "user_context": {"user_id": 7},
                        "event_data": {"file_id": 101, "entry_point": "natural"},
                    },
                },
                {
                    "sort": [1_784_070_401, "b"],
                    "_source": {
                        "timestamp": 1_784_070_401,
                        "user_context": {"user_id": 8},
                        "event_data": {"file_id": 102, "entry_point": "home_recommendation"},
                    },
                },
            ]
        else:
            hits = [
                {
                    "sort": [1_784_070_402, "c"],
                    "_source": {
                        "timestamp": 1_784_070_402,
                        "user_context": {"user_id": 9},
                        "event_data": {"file_id": 103, "entry_point": "search"},
                    },
                }
            ]
        return {"hits": {"hits": hits}}


@pytest.mark.asyncio
async def test_recent_search_query_is_strictly_scoped_by_context_tenant_user_event_and_utc_window():
    client = _FakeEsClient()
    repository = PortalRecommendationTelemetryRepositoryImpl(es_client=client)
    since = datetime(2026, 4, 16, tzinfo=timezone.utc)
    token = current_tenant_id.set(5)
    try:
        signals = await repository.list_recent_search_queries(5, 7, since, 20)
    finally:
        current_tenant_id.reset(token)

    body = client.search_calls[0]["body"]
    filters = body["query"]["bool"]["filter"]
    assert {"term": {"tenant_id": 5}} in filters
    assert {"term": {"user_context.user_id": 7}} in filters
    assert {"term": {"event_type": "portal_search"}} in filters
    assert {"range": {"timestamp": {"gte": int(since.timestamp())}}} in filters
    assert body["aggs"]["queries"]["terms"]["size"] == 20
    document = BaseTelemetryEvent(
        tenant_id=5,
        event_type=BaseTelemetryTypeEnum.PORTAL_SEARCH,
        user_context=UserContext(user_id=7, user_name="user-7"),
        event_data=PortalSearchEventData(
            source_app="shougang_portal",
            scene="knowledge_search",
            entry_point="search_page",
            query="Safety",
            normalized_query="safety",
        ),
    ).model_dump()
    assert document["event_data"]["normalized_query"] == "safety"
    assert body["aggs"]["queries"]["terms"]["field"] == "event_data.normalized_query.keyword"
    assert [(item.query, item.count) for item in signals] == [("steel", 3), ("safety", 1)]


@pytest.mark.asyncio
async def test_expired_search_delete_cannot_delete_other_tenant_event_or_recent_boundary():
    client = _FakeEsClient()
    repository = PortalRecommendationTelemetryRepositoryImpl(es_client=client)
    before = datetime(2026, 4, 16, tzinfo=timezone.utc)
    token = current_tenant_id.set(5)
    try:
        deleted = await repository.delete_expired_searches(5, before)
    finally:
        current_tenant_id.reset(token)

    filters = client.delete_calls[0]["body"]["query"]["bool"]["filter"]
    assert filters == [
        {"term": {"tenant_id": 5}},
        {"term": {"event_type": "portal_search"}},
        {"range": {"timestamp": {"lt": int(before.timestamp())}}},
    ]
    assert deleted == 7


@pytest.mark.asyncio
async def test_repository_rejects_caller_tenant_that_does_not_match_context():
    repository = PortalRecommendationTelemetryRepositoryImpl(es_client=_FakeEsClient())
    token = current_tenant_id.set(5)
    try:
        with pytest.raises(PermissionError):
            await repository.list_recent_search_queries(
                1,
                7,
                datetime.now(timezone.utc) - timedelta(days=90),
                20,
            )
    finally:
        current_tenant_id.reset(token)


@pytest.mark.asyncio
async def test_recent_document_views_use_search_after_until_all_facts_are_loaded():
    client = _PagedViewsEsClient()
    repository = PortalRecommendationTelemetryRepositoryImpl(es_client=client)
    repository.DOCUMENT_VIEW_PAGE_SIZE = 2
    since = datetime(2026, 6, 15, tzinfo=timezone.utc)
    before = datetime(2026, 7, 15, tzinfo=timezone.utc)
    token = current_tenant_id.set(5)
    try:
        views = await repository.list_recent_document_views(5, since, before, None)
    finally:
        current_tenant_id.reset(token)

    assert [view.file_id for view in views] == [101, 102, 103]
    assert len(client.search_calls) == 2
    first_body = client.search_calls[0]["body"]
    second_body = client.search_calls[1]["body"]
    assert "search_after" not in first_body
    assert second_body["search_after"] == [1_784_070_401, "b"]
    assert first_body["sort"] == [{"timestamp": "asc"}, {"event_id": "asc"}]
    assert {"term": {"tenant_id": 5}} in first_body["query"]["bool"]["filter"]
    assert {
        "range": {
            "timestamp": {
                "gte": int(since.timestamp()),
                "lte": int(before.timestamp()),
            }
        }
    } in first_body["query"]["bool"]["filter"]


@pytest.mark.asyncio
async def test_recent_document_views_deduplicate_each_shanghai_natural_day_across_pages():
    class _DuplicateViewsEsClient:
        def __init__(self):
            self.search_calls = []

        async def search(self, **kwargs):
            self.search_calls.append(kwargs)
            pages = [
                [int(datetime(2026, 7, 14, 16, 30, tzinfo=timezone.utc).timestamp())],
                [int(datetime(2026, 7, 15, 15, 30, tzinfo=timezone.utc).timestamp())],
                [],
            ]
            timestamps = pages[min(len(self.search_calls) - 1, 2)]
            return {
                "hits": {
                    "hits": [
                        {
                            "sort": [timestamp, f"event-{timestamp}"],
                            "_source": {
                                "timestamp": timestamp,
                                "user_context": {"user_id": 7},
                                "event_data": {"file_id": 101, "entry_point": "natural"},
                            },
                        }
                        for timestamp in timestamps
                    ]
                }
            }

    client = _DuplicateViewsEsClient()
    repository = PortalRecommendationTelemetryRepositoryImpl(es_client=client)
    repository.DOCUMENT_VIEW_PAGE_SIZE = 1
    token = current_tenant_id.set(5)
    try:
        views = await repository.list_recent_document_views(
            5,
            datetime(2026, 7, 14, tzinfo=timezone.utc),
            datetime(2026, 7, 16, tzinfo=timezone.utc),
            None,
        )
    finally:
        current_tenant_id.reset(token)

    assert len(views) == 1
    assert views[0].viewed_at == datetime(2026, 7, 15, 15, 30, tzinfo=timezone.utc)
