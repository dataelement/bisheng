"""门户首页问答计数: 文档问答事件 + 看板专家/智能问答事实."""

import pytest

from bisheng.common.constants.telemetry import (
    HOME_STATS_EXTRA_QA_TYPES,
    REALTIME_QA_QUESTION_FACT_INDEX,
)
from bisheng.common.telemetry.portal_event_service import PortalTelemetryEventService


class _FakeSearchClient:
    def __init__(self, *, qa_value: int = 0) -> None:
        self.qa_value = qa_value
        self.search_calls: list[dict] = []

    async def search(self, **kwargs):
        self.search_calls.append(kwargs)
        return {"aggregations": {"qa_count": {"value": self.qa_value}}}


@pytest.mark.asyncio
async def test_count_dashboard_qa_by_types_uses_fact_index(monkeypatch: pytest.MonkeyPatch):
    fake_client = _FakeSearchClient(qa_value=9)

    async def fake_get_es_connection():
        return fake_client

    monkeypatch.setattr(
        "bisheng.common.telemetry.portal_event_service.get_statistics_es_connection",
        fake_get_es_connection,
    )

    result = await PortalTelemetryEventService.count_dashboard_qa_by_types(HOME_STATS_EXTRA_QA_TYPES)

    assert result == 9
    assert fake_client.search_calls == [
        {
            "index": REALTIME_QA_QUESTION_FACT_INDEX,
            "body": {
                "size": 0,
                "query": {
                    "bool": {
                        "filter": [
                            {"terms": {"qa_type": ["expert", "smart"]}},
                        ]
                    }
                },
                "aggs": {
                    "qa_count": {
                        "value_count": {
                            "field": "question_id",
                        }
                    }
                },
            },
            "filter_path": "aggregations.qa_count.value",
        }
    ]


@pytest.mark.asyncio
async def test_count_dashboard_qa_by_types_empty() -> None:
    assert await PortalTelemetryEventService.count_dashboard_qa_by_types(()) == 0
