"""门户首页问答计数使用看板事实表的历史累计总量。"""

import pytest

from bisheng.common.constants.telemetry import (
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
@pytest.mark.parametrize("qa_value", [0, 9])
async def test_count_dashboard_qa_uses_all_history_and_dashboard_connection(monkeypatch: pytest.MonkeyPatch, qa_value):
    fake_client = _FakeSearchClient(qa_value=qa_value)

    async def fake_get_es_connection():
        return fake_client

    monkeypatch.setattr(
        "bisheng.common.telemetry.portal_event_service.get_es_connection",
        fake_get_es_connection,
    )

    result = await PortalTelemetryEventService.count_dashboard_qa()

    assert result == qa_value
    assert fake_client.search_calls == [
        {
            "index": REALTIME_QA_QUESTION_FACT_INDEX,
            "body": {
                "size": 0,
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
