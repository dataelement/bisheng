import sys

import pytest

for module_name in (
    "bisheng.common.services",
    "bisheng.common.services.telemetry",
    "bisheng.common.services.telemetry.telemetry_service",
):
    sys.modules.pop(module_name, None)

from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum  # noqa: E402
from bisheng.common.schemas.telemetry.base_telemetry_schema import BaseTelemetryEvent, UserContext  # noqa: E402
from bisheng.common.schemas.telemetry.event_data_schema import (  # noqa: E402
    PortalDocumentReadEventData,
    PortalFavoriteEventData,
    PortalQaEventData,
)
from bisheng.common.telemetry.portal_event_service import PortalTelemetryEventService  # noqa: E402


def test_portal_telemetry_event_types_and_schemas():
    assert BaseTelemetryTypeEnum.PORTAL_FAVORITE.value == "portal_favorite"
    assert BaseTelemetryTypeEnum.PORTAL_QA.value == "portal_qa"
    assert BaseTelemetryTypeEnum.PORTAL_DOCUMENT_READ.value == "portal_document_read"

    event = BaseTelemetryEvent(
        event_type=BaseTelemetryTypeEnum.PORTAL_FAVORITE,
        user_context=UserContext(user_id=7, user_name="user-7"),
        event_data=PortalFavoriteEventData(
            source_app="shougang_portal",
            scene="search_result_favorite",
            entry_point="search_result_favorite",
            resource_type="document",
            source_space_id=12,
            source_file_id=1580,
            target_space_id=7201,
            status="success",
        ),
    )

    dumped = event.model_dump()
    assert dumped["event_type"] == "portal_favorite"
    assert dumped["event_data"]["portal_favorite_scene"] == "search_result_favorite"
    assert dumped["event_data"]["portal_favorite_source_file_id"] == 1580
    assert "query" not in dumped["event_data"]
    assert "answer" not in dumped["event_data"]


def test_portal_telemetry_service_builds_event_data():
    qa = PortalTelemetryEventService.build_event_data(
        BaseTelemetryTypeEnum.PORTAL_QA,
        {
            "source_app": "bisheng_my_knowledge",
            "scene": "my_knowledge_document_qa",
            "entry_point": "my_knowledge_document_qa",
            "resource_type": "document",
            "space_id": 12,
            "file_id": 1580,
            "status": "success",
        },
    )
    read = PortalTelemetryEventService.build_event_data(
        BaseTelemetryTypeEnum.PORTAL_DOCUMENT_READ,
        {
            "source_app": "bisheng_my_knowledge",
            "scene": "document_preview",
            "entry_point": "my_knowledge_preview",
            "resource_type": "document",
            "space_id": 12,
            "file_id": 1580,
            "status": "success",
        },
    )

    assert isinstance(qa, PortalQaEventData)
    assert isinstance(read, PortalDocumentReadEventData)


def test_portal_telemetry_recorder_is_best_effort(monkeypatch):
    def raise_runtime_error(**_kwargs):
        raise RuntimeError("telemetry unavailable")

    monkeypatch.setattr(
        "bisheng.common.telemetry.portal_event_service.telemetry_service.log_event_sync",
        raise_runtime_error,
    )

    PortalTelemetryEventService.log_event_sync(
        user_id=7,
        event_type=BaseTelemetryTypeEnum.PORTAL_DOCUMENT_READ,
        event_data=PortalDocumentReadEventData(
            source_app="bisheng_my_knowledge",
            scene="document_preview",
            entry_point="my_knowledge_preview",
            resource_type="document",
            space_id=12,
            file_id=1580,
            status="success",
        ),
    )


@pytest.mark.asyncio
async def test_portal_home_event_counts(monkeypatch):
    class FakeEsClient:
        async def search(self, **kwargs):
            assert kwargs["index"] == "base_telemetry_events"
            assert kwargs["body"]["query"] == {
                "terms": {
                    "event_type": [
                        "portal_document_read",
                        "portal_favorite",
                        "portal_qa",
                    ]
                }
            }
            return {
                "aggregations": {
                    "by_event_type": {
                        "buckets": [
                            {"key": "portal_document_read", "doc_count": 11},
                            {"key": "portal_favorite", "doc_count": 3},
                            {"key": "portal_qa", "doc_count": 5},
                        ]
                    }
                }
            }

    async def fake_get_statistics_es_connection():
        return FakeEsClient()

    monkeypatch.setattr(
        "bisheng.common.telemetry.portal_event_service.get_statistics_es_connection",
        fake_get_statistics_es_connection,
    )

    assert await PortalTelemetryEventService.count_home_events() == {
        "read_count": 11,
        "favorite_count": 3,
        "qa_count": 5,
    }


@pytest.mark.asyncio
async def test_portal_document_read_counts_by_space_ids(monkeypatch):
    class FakeEsClient:
        async def search(self, **kwargs):
            assert kwargs["index"] == "base_telemetry_events"
            body = kwargs["body"]
            filters = body["query"]["bool"]["filter"]
            assert {"term": {"event_type": "portal_document_read"}} in filters
            assert {"term": {"event_data.portal_document_read_source_app": "shougang_portal"}} in filters
            assert {"terms": {"event_data.portal_document_read_space_id": [12, 13]}} in filters
            terms = body["aggs"]["by_file"]["terms"]
            assert terms["field"] == "event_data.portal_document_read_file_id"
            assert terms["order"] == [{"_count": "desc"}, {"_key": "asc"}]
            assert body["aggs"]["by_file"]["aggs"]["bucket_page"]["bucket_sort"] == {
                "from": 2,
                "size": 3,
            }
            return {
                "aggregations": {
                    "by_file": {
                        "buckets": [
                            {"key": "101", "doc_count": 9},
                            {"key": 102, "doc_count": 7},
                            {"key": "invalid", "doc_count": 5},
                        ]
                    }
                }
            }

    async def fake_get_statistics_es_connection():
        return FakeEsClient()

    monkeypatch.setattr(
        "bisheng.common.telemetry.portal_event_service.get_statistics_es_connection",
        fake_get_statistics_es_connection,
    )

    assert await PortalTelemetryEventService.list_document_read_counts_by_space_ids(
        [12, 13, 12],
        offset=2,
        limit=3,
    ) == [
        {"file_id": 101, "read_count": 9},
        {"file_id": 102, "read_count": 7},
    ]
