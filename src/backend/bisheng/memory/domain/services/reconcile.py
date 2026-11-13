"""Index and object-store reconciliation for one tenant (design decisions 5, 12, pit 10).

- items still ``pending`` are indexed again;
- items indexed with an embedding model other than the tenant's current one are
  re-indexed (the old collection is no longer read);
- detail objects that no item row points to are deleted.
Runs with the tenant context already set by the caller.
"""

from __future__ import annotations

import time

from loguru import logger
from sqlalchemy import or_
from sqlmodel import select

from bisheng.memory.domain.models.memory_item import INDEX_PENDING, STATUS_ACTIVE, MemoryItem
from bisheng.memory.domain.ports import MemoryContext
from bisheng.memory.domain.repositories import _db
from bisheng.memory.domain.repositories.item_repository import ItemRepository

BATCH = 200
ORPHAN_GRACE_SECONDS = 3600
ORPHAN_MARKER_TTL = 3 * 86400


async def _users_of_tenant(tenant_id: int) -> list[int]:
    async with _db.async_session() as s:
        rows = (await s.exec(select(MemoryItem.user_id).where(MemoryItem.tenant_id == tenant_id).distinct())).all()
    return [int(u) for u in rows]


async def reconcile_user(ctx: MemoryContext, service) -> None:
    current_model = await service.index.current_model_id(ctx)
    async with _db.async_session() as s:
        stmt = select(MemoryItem).where(
            MemoryItem.tenant_id == ctx.tenant_id,
            MemoryItem.user_id == ctx.user_id,
            MemoryItem.status == STATUS_ACTIVE,
        )
        if current_model:
            stmt = stmt.where(
                or_(
                    MemoryItem.index_state == INDEX_PENDING,
                    MemoryItem.index_model_id.is_(None),
                    MemoryItem.index_model_id != current_model,
                )
            )
        else:
            stmt = stmt.where(MemoryItem.index_state == INDEX_PENDING)
        items = list((await s.exec(stmt.limit(BATCH))).all())
    if items:
        await service.index_items(ctx, items)
    async with _db.async_session() as s:
        referenced = set(await ItemRepository.list_detail_keys(s, ctx))
    now = time.time()
    for key in await service.details.list_keys(ctx):
        marker = f"memory:orphan:{key}"
        if key in referenced:
            continue
        # A detail object is written before its row commits (decision 3). Delete only
        # objects still unreferenced a grace period after they were first seen orphaned.
        first_seen = await service.kv.get(marker)
        if first_seen is None:
            await service.kv.set(marker, str(now), ORPHAN_MARKER_TTL)
        elif now - float(first_seen) >= ORPHAN_GRACE_SECONDS:
            await service.details.delete(key)
            await service.kv.delete(marker)


async def reconcile_tenant(tenant_id: int, service) -> None:
    for user_id in await _users_of_tenant(tenant_id):
        try:
            await reconcile_user(MemoryContext(tenant_id=tenant_id, user_id=user_id), service)
        except Exception:
            # One user's index or store hiccup must not stop the others; retried next hour.
            logger.exception("memory reconcile failed tenant={} user={}", tenant_id, user_id)
