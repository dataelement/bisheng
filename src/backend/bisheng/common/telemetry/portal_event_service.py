import logging
from typing import Any

from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum
from bisheng.common.schemas.telemetry.event_data_schema import (
    PortalDocumentReadEventData,
    PortalFavoriteEventData,
    PortalQaEventData,
)
from bisheng.common.services import telemetry_service
from bisheng.core.logger import trace_id_var
from bisheng.core.search.elasticsearch.manager import get_statistics_es_connection

logger = logging.getLogger(__name__)

PORTAL_BFF_TELEMETRY_SOURCE_HEADER = "X-Portal-Telemetry-Source"
PORTAL_BFF_TELEMETRY_SOURCE = "shougang_portal_bff"

PORTAL_HOME_EVENT_TYPES = (
    BaseTelemetryTypeEnum.PORTAL_DOCUMENT_READ,
    BaseTelemetryTypeEnum.PORTAL_FAVORITE,
    BaseTelemetryTypeEnum.PORTAL_QA,
)


class PortalTelemetryEventService:
    """Best-effort recorder and stats reader for Shougang portal events."""

    _event_data_classes = {
        BaseTelemetryTypeEnum.PORTAL_FAVORITE: PortalFavoriteEventData,
        BaseTelemetryTypeEnum.PORTAL_QA: PortalQaEventData,
        BaseTelemetryTypeEnum.PORTAL_DOCUMENT_READ: PortalDocumentReadEventData,
    }

    @classmethod
    def build_event_data(
        cls,
        event_type: BaseTelemetryTypeEnum,
        payload: dict[str, Any],
    ) -> PortalFavoriteEventData | PortalQaEventData | PortalDocumentReadEventData:
        data_cls = cls._event_data_classes[event_type]
        return data_cls(**payload)

    @classmethod
    def log_event_sync(
        cls,
        *,
        user_id: int,
        event_type: BaseTelemetryTypeEnum,
        event_data: PortalFavoriteEventData | PortalQaEventData | PortalDocumentReadEventData,
    ) -> None:
        try:
            telemetry_service.log_event_sync(
                user_id=user_id,
                event_type=event_type,
                trace_id=trace_id_var.get(),
                event_data=event_data,
            )
        except (RuntimeError, ValueError, TypeError):
            logger.exception(
                "Failed to enqueue portal telemetry event user_id=%s event_type=%s scene=%s entry_point=%s",
                user_id,
                event_type.value,
                getattr(event_data, "scene", ""),
                getattr(event_data, "entry_point", ""),
            )

    @staticmethod
    async def count_file_views(file_id: int) -> int:
        """Return the total number of PORTAL_DOCUMENT_READ events for a specific file."""
        body = {
            "size": 0,
            "query": {
                "bool": {
                    "must": [
                        {"term": {"event_type": BaseTelemetryTypeEnum.PORTAL_DOCUMENT_READ.value}},
                        {"term": {"file_id": file_id}},
                    ]
                }
            },
        }
        try:
            es_client = await get_statistics_es_connection()
            response = await es_client.search(index=telemetry_service.index_name, body=body)
            return int(response.get("hits", {}).get("total", {}).get("value", 0))
        except Exception:
            logger.exception("Failed to count file views for file_id=%s", file_id)
            return 0

    @staticmethod
    async def count_home_events() -> dict[str, int]:
        event_values = [event_type.value for event_type in PORTAL_HOME_EVENT_TYPES]
        body = {
            "size": 0,
            "query": {"terms": {"event_type": event_values}},
            "aggs": {
                "by_event_type": {
                    "terms": {
                        "field": "event_type",
                        "size": len(event_values),
                    }
                }
            },
        }
        es_client = await get_statistics_es_connection()
        response = await es_client.search(index=telemetry_service.index_name, body=body)
        buckets = response.get("aggregations", {}).get("by_event_type", {}).get("buckets", [])
        counts = dict.fromkeys(event_values, 0)
        for bucket in buckets:
            key = str(bucket.get("key") or "")
            if key in counts:
                counts[key] = int(bucket.get("doc_count") or 0)
        return {
            "read_count": counts[BaseTelemetryTypeEnum.PORTAL_DOCUMENT_READ.value],
            "favorite_count": counts[BaseTelemetryTypeEnum.PORTAL_FAVORITE.value],
            "qa_count": counts[BaseTelemetryTypeEnum.PORTAL_QA.value],
        }


def is_portal_bff_proxy_source(source: str | None) -> bool:
    return (source or "").strip() == PORTAL_BFF_TELEMETRY_SOURCE
