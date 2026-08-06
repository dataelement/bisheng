from types import SimpleNamespace

import pytest

from bisheng.common.telemetry import portal_event_service
from bisheng.knowledge.api.endpoints import shougang_portal


class _FakeSearchClient:
    def __init__(self, *, total: int = 0) -> None:
        self.total = total
        self.search_calls: list[dict] = []

    async def search(self, **kwargs):
        self.search_calls.append(kwargs)
        return {
            "aggregations": {
                "total_file_count": {
                    "value": self.total,
                }
            }
        }


@pytest.mark.asyncio
async def test_portal_file_count_uses_dashboard_es_metric(monkeypatch: pytest.MonkeyPatch):
    fake_client = _FakeSearchClient(total=41)

    async def fake_get_es_connection():
        return fake_client

    monkeypatch.setattr(
        portal_event_service,
        "get_statistics_es_connection",
        fake_get_es_connection,
    )

    result = await portal_event_service.PortalTelemetryEventService.count_dashboard_files()

    assert result == 41
    assert fake_client.search_calls == [
        {
            "index": "mid_knowledge_space_content_stat",
            "body": {
                "size": 0,
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"record_type": "file"}},
                            {"term": {"file_type": 1}},
                            {
                                "terms": {
                                    "space_level": [
                                        "public",
                                        "department",
                                        "team",
                                        "team_ks",
                                    ]
                                }
                            },
                        ]
                    }
                },
                "aggs": {
                    "total_file_count": {
                        "value_count": {
                            "field": "file_id",
                        }
                    }
                },
            },
            "filter_path": "aggregations.total_file_count.value",
        }
    ]


@pytest.mark.asyncio
async def test_portal_home_stats_uses_es_file_count(monkeypatch: pytest.MonkeyPatch):
    async def fake_count_home_events():
        return {
            "read_count": 12,
            "favorite_count": 3,
            "qa_count": 7,
        }

    async def fake_count_dashboard_files():
        return 41

    monkeypatch.setattr(
        shougang_portal.PortalTelemetryEventService,
        "count_home_events",
        fake_count_home_events,
    )
    monkeypatch.setattr(
        shougang_portal.PortalTelemetryEventService,
        "count_dashboard_files",
        fake_count_dashboard_files,
    )

    response = await shougang_portal.get_shougang_portal_home_stats(
        login_user=SimpleNamespace(user_id=1),
    )

    assert response.data == {
        "read_count": 12,
        "favorite_count": 3,
        "qa_count": 7,
        "total_files": 41,
    }


@pytest.mark.asyncio
async def test_portal_home_stats_propagates_es_file_count_failure(monkeypatch: pytest.MonkeyPatch):
    async def fake_count_home_events():
        return {
            "read_count": 12,
            "favorite_count": 3,
            "qa_count": 7,
        }

    async def fail_count_dashboard_files():
        raise RuntimeError("statistics es unavailable")

    monkeypatch.setattr(
        shougang_portal.PortalTelemetryEventService,
        "count_home_events",
        fake_count_home_events,
    )
    monkeypatch.setattr(
        shougang_portal.PortalTelemetryEventService,
        "count_dashboard_files",
        fail_count_dashboard_files,
    )

    with pytest.raises(RuntimeError, match="statistics es unavailable"):
        await shougang_portal.get_shougang_portal_home_stats(
            login_user=SimpleNamespace(user_id=1),
        )
