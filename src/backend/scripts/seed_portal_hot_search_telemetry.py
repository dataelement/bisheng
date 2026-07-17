"""Seed portal_search telemetry events for hot-search pipeline testing.

Creates 20 manual search events (entry_point=search_page) from 5 users across
2 days so the default thresholds (min_unique_users=5, min_search_count=8) can
be satisfied after rebuild.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum
from bisheng.common.schemas.telemetry.base_telemetry_schema import BaseTelemetryEvent, UserContext
from bisheng.common.schemas.telemetry.event_data_schema import PortalSearchEventData
from bisheng.common.services.telemetry.telemetry_service import telemetry_service
from bisheng.core.context.tenant import DEFAULT_TENANT_ID, set_current_tenant_id
from bisheng.core.search.elasticsearch.manager import get_statistics_es_connection

USERS: list[tuple[int, str]] = [
    (1001, "AAA"),
    (1002, "BBB"),
    (1003, "CCC"),
    (1004, "DDD"),
    (1005, "EEE"),
]

HOT_SEARCH_QUERY = "设备检修安全要求"
NORMALIZED_QUERY = HOT_SEARCH_QUERY.casefold()
EVENTS_PER_USER = 4  # 2 days x 2 searches per day
DAY_OFFSETS = (0, 1)


async def seed_events(*, tenant_id: int = DEFAULT_TENANT_ID) -> int:
    set_current_tenant_id(tenant_id)
    client = await get_statistics_es_connection()
    now = datetime.now(timezone.utc)
    docs: list[dict] = []

    for user_id, user_name in USERS:
        for day_offset in DAY_OFFSETS:
            day_base = now - timedelta(days=day_offset)
            for duplicate in range(EVENTS_PER_USER // len(DAY_OFFSETS)):
                searched_at = day_base - timedelta(minutes=duplicate * 7 + user_id % 5)
                event = BaseTelemetryEvent(
                    tenant_id=tenant_id,
                    event_type=BaseTelemetryTypeEnum.PORTAL_SEARCH,
                    timestamp=int(searched_at.timestamp()),
                    user_context=UserContext(user_id=user_id, user_name=user_name),
                    event_data=PortalSearchEventData(
                        source_app="shougang_portal",
                        scene="knowledge_search",
                        entry_point="search_page",
                        resource_type="search_query",
                        status="success",
                        query=HOT_SEARCH_QUERY,
                        normalized_query=NORMALIZED_QUERY,
                    ),
                )
                docs.append(event.model_dump())

    assert len(docs) == len(USERS) * EVENTS_PER_USER == 20

    for doc in docs:
        await client.index(index=telemetry_service.index_name, document=doc)

    return len(docs)


async def main() -> None:
    count = await seed_events()
    print(
        f"Indexed {count} portal_search events "
        f"(users={','.join(name for _, name in USERS)}, query={HOT_SEARCH_QUERY!r})"
    )


if __name__ == "__main__":
    asyncio.run(main())
