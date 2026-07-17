"""Seed portal_search telemetry events for hot-search pipeline testing.

Writes manual ``portal_search`` events (``entry_point=search_page``) to ES so
rebuild can produce Top-K hot searches. Default: 5 users (AAA–EEE) × 5 queries ×
4 searches (2 days × 2/day) = 100 events; each query gets 10 user-day deduped
hits (≥ default ``min_search_count=8`` and ``min_unique_users=5``).

Usage (from ``src/backend/``)::

    PYTHONPATH=. uv run python scripts/seed_portal_hot_search_telemetry.py
    PYTHONPATH=. uv run python scripts/seed_portal_hot_search_telemetry.py --rebuild
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum  # noqa: E402
from bisheng.common.schemas.telemetry.base_telemetry_schema import BaseTelemetryEvent, UserContext  # noqa: E402
from bisheng.common.schemas.telemetry.event_data_schema import PortalSearchEventData  # noqa: E402
from bisheng.common.services.telemetry.telemetry_service import telemetry_service  # noqa: E402
from bisheng.core.context.tenant import DEFAULT_TENANT_ID, set_current_tenant_id  # noqa: E402
from bisheng.core.search.elasticsearch.manager import get_statistics_es_connection  # noqa: E402

USERS: list[tuple[int, str]] = [
    (1001, "AAA"),
    (1002, "BBB"),
    (1003, "CCC"),
    (1004, "DDD"),
    (1005, "EEE"),
]

DEFAULT_QUERIES: list[str] = [
    "设备检修安全要求",
    "能源管理制度",
    "环保设施运行标准",
    "安全生产责任清单",
    "故障诊断处理方法",
]

DAY_OFFSETS = (0, 1, 2, 3)
DUPLICATES_PER_DAY = 2


def _build_events(
    *,
    tenant_id: int,
    queries: list[str],
    now: datetime,
) -> list[dict]:
    docs: list[dict] = []
    for query in queries:
        normalized = query.casefold()
        for user_id, user_name in USERS:
            for day_offset in DAY_OFFSETS:
                day_base = now - timedelta(days=day_offset)
                for duplicate in range(DUPLICATES_PER_DAY):
                    searched_at = day_base - timedelta(
                        minutes=duplicate * 11 + (user_id % 7) + len(query) % 5,
                    )
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
                            query=query,
                            normalized_query=normalized,
                        ),
                    )
                    docs.append(event.model_dump())
    return docs


async def seed_events(
    *,
    tenant_id: int = DEFAULT_TENANT_ID,
    queries: list[str] | None = None,
) -> int:
    queries = queries or DEFAULT_QUERIES
    set_current_tenant_id(tenant_id)
    client = await get_statistics_es_connection()
    docs = _build_events(tenant_id=tenant_id, queries=queries, now=datetime.now(timezone.utc))

    for doc in docs:
        await client.index(index=telemetry_service.index_name, document=doc)

    return len(docs)


async def _rebuild_tenant(tenant_id: int) -> str:
    from bisheng.worker.knowledge.portal_hot_search import _rebuild_async

    set_current_tenant_id(tenant_id)
    return await _rebuild_async(now=datetime.now(timezone.utc))


async def run(args: argparse.Namespace) -> int:
    queries = args.queries or DEFAULT_QUERIES
    count = await seed_events(tenant_id=args.tenant_id, queries=queries)
    per_query = len(USERS) * len(DAY_OFFSETS) * DUPLICATES_PER_DAY
    print(
        f"Indexed {count} portal_search events "
        f"(tenant={args.tenant_id}, users={','.join(name for _, name in USERS)}, "
        f"queries={len(queries)}, ~{per_query}/query)"
    )
    for idx, query in enumerate(queries, start=1):
        print(f"  {idx}. {query}")

    if args.rebuild:
        status = await _rebuild_tenant(args.tenant_id)
        print(f"Rebuild finished: {status}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", type=int, default=DEFAULT_TENANT_ID)
    parser.add_argument(
        "--queries",
        nargs="+",
        help="Search queries to seed (default: 5 built-in Chinese queries)",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Run hot-search rebuild for the tenant after seeding",
    )
    args = parser.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
