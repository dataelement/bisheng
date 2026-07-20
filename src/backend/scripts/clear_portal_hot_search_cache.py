"""Clear portal hot-search Redis cache (and optional rebuild lock).

Deletes ``portal:hot_search:{tenant_id}`` and ``portal:hot_search:lock:{tenant_id}``
keys (with tenant prefix when applicable). MySQL snapshot is untouched; the next
home read falls back to DB and may backfill Redis.

Usage (from ``src/backend/``)::

    PYTHONPATH=. uv run python scripts/clear_portal_hot_search_cache.py
    PYTHONPATH=. uv run python scripts/clear_portal_hot_search_cache.py --tenant-id 1
    PYTHONPATH=. uv run python scripts/clear_portal_hot_search_cache.py --all-tenants
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from bisheng.core.cache.redis_manager import get_redis_client  # noqa: E402
from bisheng.core.context.tenant import DEFAULT_TENANT_ID  # noqa: E402
from bisheng.core.storage.tenant_storage import get_redis_key_prefix  # noqa: E402
from bisheng.database.models.tenant import TenantDao  # noqa: E402


def _keys_for_tenant(tenant_id: int) -> tuple[str, str]:
    prefix = get_redis_key_prefix(tenant_id)
    return (
        f"{prefix}portal:hot_search:{tenant_id}",
        f"{prefix}portal:hot_search:lock:{tenant_id}",
    )


async def clear_tenant_cache(tenant_id: int, *, include_lock: bool = True) -> list[str]:
    redis = await get_redis_client()
    cache_key, lock_key = _keys_for_tenant(tenant_id)
    keys = [cache_key]
    if include_lock:
        keys.append(lock_key)
    deleted: list[str] = []
    for key in keys:
        removed = await redis.async_connection.delete(key)
        if removed:
            deleted.append(key)
    return deleted


async def clear_all_tenant_caches(*, include_lock: bool = True) -> list[str]:
    tenant_ids = [DEFAULT_TENANT_ID]
    children = await TenantDao.aget_children_ids_active(DEFAULT_TENANT_ID)
    tenant_ids.extend(int(tid) for tid in children if int(tid) > 0)
    deleted: list[str] = []
    for tenant_id in sorted(set(tenant_ids)):
        deleted.extend(await clear_tenant_cache(tenant_id, include_lock=include_lock))
    return deleted


async def run(args: argparse.Namespace) -> int:
    if args.all_tenants:
        deleted = await clear_all_tenant_caches(include_lock=not args.cache_only)
    else:
        deleted = await clear_tenant_cache(args.tenant_id, include_lock=not args.cache_only)

    if deleted:
        print("Deleted Redis keys:")
        for key in deleted:
            print(f"  - {key}")
    else:
        target = "all active tenants" if args.all_tenants else f"tenant_id={args.tenant_id}"
        print(f"No hot-search Redis keys found for {target}.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", type=int, default=DEFAULT_TENANT_ID)
    parser.add_argument(
        "--all-tenants",
        action="store_true",
        help="Clear cache for root tenant and all active child tenants",
    )
    parser.add_argument(
        "--cache-only",
        action="store_true",
        help="Delete snapshot cache only; keep rebuild lock key",
    )
    args = parser.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
