"""Memory metrics: Redis counters flushed daily into memory_metric_daily (decision 20).

Counters are keyed by tenant, scene and app; nothing here ever holds content
(AC-103). Read sets ("items read today", "details read today") are flushed into
``memory_item.last_read_at`` / ``detail_read_at`` so "never read" and "detail
read ratio" can be computed from the item table.
"""

from __future__ import annotations

from datetime import datetime

from loguru import logger
from sqlalchemy import func
from sqlmodel import select

from bisheng.memory.domain.models.memory_item import STATUS_ACTIVE, MemoryItem
from bisheng.memory.domain.models.memory_metric_daily import MemoryMetricDaily
from bisheng.memory.domain.ports import MemoryContext
from bisheng.memory.domain.repositories import _db

ADDED_EXPLICIT = "added_explicit"
ADDED_AUTO = "added_auto"
ADDED_MANUAL = "added_manual"
SUPERSEDED = "superseded"
DELETED = "deleted"
INJECTED = "injected_items"
RETRIEVED = "retrieved_items"
UNDO = "undo"
INJECT_FAILED = "inject_failed"
SEARCH_FAILED = "search_failed"
SEARCH_DEGRADED = "search_degraded"
DETAIL_READ_FAILED = "detail_read_failed"
CONSOLIDATE_FAILED = "consolidate_failed"
ALL_COUNTERS = (
    ADDED_EXPLICIT,
    ADDED_AUTO,
    ADDED_MANUAL,
    SUPERSEDED,
    DELETED,
    INJECTED,
    RETRIEVED,
    UNDO,
    INJECT_FAILED,
    SEARCH_FAILED,
    SEARCH_DEGRADED,
    DETAIL_READ_FAILED,
    CONSOLIDATE_FAILED,
)

_COUNTER_KEY = "memory:metric:{day}:{tenant}"
_READ_KEY = "memory:read:{day}:{tenant}:{user}"
_DETAIL_KEY = "memory:detail:{day}:{tenant}:{user}"


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


class MemoryMetrics:
    def __init__(self, kv):
        self._kv = kv

    async def incr(self, ctx: MemoryContext, metric: str, amount: int = 1) -> None:
        if amount <= 0:
            return
        field = f"{ctx.scene or ''}|{ctx.app_id or ''}|{metric}"
        try:
            await self._kv.hincrby(_COUNTER_KEY.format(day=_today(), tenant=ctx.tenant_id), field, amount)
        except Exception:
            # Telemetry only: never break the user's turn for a counter.
            logger.exception("memory metric incr failed metric={}", metric)

    async def mark_read(self, ctx: MemoryContext, item_ids: list[str]) -> None:
        await self._sadd(_READ_KEY, ctx, item_ids)

    async def mark_detail_read(self, ctx: MemoryContext, item_ids: list[str]) -> None:
        await self._sadd(_DETAIL_KEY, ctx, item_ids)

    async def _sadd(self, pattern, ctx, item_ids):
        if not item_ids:
            return
        try:
            await self._kv.sadd(pattern.format(day=_today(), tenant=ctx.tenant_id, user=ctx.user_id), *item_ids)
        except Exception:
            logger.exception("memory read-set update failed")

    async def flush(self, day: str | None = None) -> None:
        """Move counters and read sets of ``day`` (default today) into the database."""
        day = day or _today()
        for key in await self._kv.keys(_COUNTER_KEY.format(day=day, tenant="*")):
            tenant_id = int(key.rsplit(":", 1)[1])
            counts = await self._kv.hgetall(key)
            await self._kv.delete(key)
            async with _db.async_session() as s:
                for field, value in counts.items():
                    scene, app_id, metric = field.split("|", 2)
                    row = (
                        await s.exec(
                            select(MemoryMetricDaily).where(
                                MemoryMetricDaily.day == day,
                                MemoryMetricDaily.tenant_id == tenant_id,
                                MemoryMetricDaily.scene == scene,
                                MemoryMetricDaily.app_id == app_id,
                                MemoryMetricDaily.metric == metric,
                            )
                        )
                    ).first()
                    if row is None:
                        s.add(
                            MemoryMetricDaily(
                                day=day, tenant_id=tenant_id, scene=scene, app_id=app_id, metric=metric, value=value
                            )
                        )
                    else:
                        row.value += int(value)
                        s.add(row)
                await s.commit()
        now = datetime.now()
        for pattern, column in ((_READ_KEY, "last_read_at"), (_DETAIL_KEY, "detail_read_at")):
            for key in await self._kv.keys(pattern.format(day=day, tenant="*", user="*")):
                _, _, _, tenant, user = key.split(":")
                ids = list(await self._kv.smembers(key))
                await self._kv.delete(key)
                ctx = MemoryContext(tenant_id=int(tenant), user_id=int(user))
                from bisheng.memory.domain.repositories.item_repository import ItemRepository

                async with _db.async_session() as s:
                    await ItemRepository.touch_read(s, ctx, ids, column, now)
                    await s.commit()

    async def count_never_read(self, tenant_id: int) -> int:
        async with _db.async_session() as s:
            stmt = select(func.count()).where(
                MemoryItem.tenant_id == tenant_id,
                MemoryItem.status == STATUS_ACTIVE,
                MemoryItem.last_read_at.is_(None),
            )
            return int((await s.exec(stmt)).first() or 0)

    async def detail_read_ratio(self, tenant_id: int) -> float:
        async with _db.async_session() as s:
            base = select(func.count()).where(
                MemoryItem.tenant_id == tenant_id,
                MemoryItem.status == STATUS_ACTIVE,
                MemoryItem.detail_object_key.is_not(None),
            )
            total = int((await s.exec(base)).first() or 0)
            read = int((await s.exec(base.where(MemoryItem.detail_read_at.is_not(None)))).first() or 0)
        return read / total if total else 0.0
