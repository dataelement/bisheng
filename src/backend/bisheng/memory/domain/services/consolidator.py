"""Consolidate one user's due sessions (design decision 7).

One task per (tenant, user): take the user lock (token, TTL, renewed between
sessions), re-check enablement per session, fix this run's end message id,
let the injected content function turn new messages into operations, then
commit items + rev + watermark in one transaction. Failures back off
exponentially and are counted; repeated identical failures are logged at most
hourly.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from loguru import logger

from bisheng.memory.domain.config import aget_memory_config
from bisheng.memory.domain.models.memory_session_cursor import MemorySessionCursor
from bisheng.memory.domain.repositories import _db
from bisheng.memory.domain.repositories.cursor_repository import CursorRepository
from bisheng.memory.domain.repositories.setting_repository import SettingRepository
from bisheng.memory.domain.services import metrics as m
from bisheng.memory.domain.services.app_switch import session_scene
from bisheng.memory.domain.services.gate import MemoryGate

MAX_BACKOFF = timedelta(hours=2)


def lock_key(tenant_id: int, user_id: int) -> str:
    return f"memory:consolidate:{tenant_id}:{user_id}"


def clear_marker_key(tenant_id: int, user_id: int) -> str:
    """Changes every time the user clears their memory; a run compares it before committing."""
    return f"memory:cleared:{tenant_id}:{user_id}"


class Consolidator:
    def __init__(self, service, kv, metrics: m.MemoryMetrics, content_fn, extra_steps=None):
        self.service = service
        self.kv = kv
        self.metrics = metrics
        self.content_fn = content_fn
        # Extra per-user steps (deep-research rounds, expired-event rewrite) run under the same lock.
        self.extra_steps = list(extra_steps or [])

    async def _should_log(self, tenant_id, user_id, reason: str) -> bool:
        key = f"memory:faillog:{tenant_id}:{user_id}:{reason}"
        return await self.kv.acquire(key, "1", 3600)

    async def consolidate_user(self, tenant_id: int, user_id: int, now: datetime | None = None) -> None:
        config = await aget_memory_config()
        now = now or datetime.now()
        token = uuid.uuid4().hex
        key = lock_key(tenant_id, user_id)
        ttl = config.lock_ttl_minutes * 60
        if not await self.kv.acquire(key, token, ttl):
            return
        try:
            quiet = timedelta(minutes=config.quiet_minutes)
            lock_ttl = timedelta(minutes=config.lock_ttl_minutes)
            rows = await CursorRepository.list_due_for_user(tenant_id, user_id, now, quiet, lock_ttl)
            await CursorRepository.mark_running([r.chat_id for r in rows], now)
            for index, row in enumerate(rows):
                if not await self.kv.renew(key, token, ttl):
                    # The lock expired and another node may own this user now: stop, and
                    # hand the rows not yet processed back to the next scan.
                    logger.warning("memory consolidation lost its lock tenant={} user={}", tenant_id, user_id)
                    await CursorRepository.release_running([r.chat_id for r in rows[index:]])
                    return
                await self._one_session(row, config, now)
            for step in self.extra_steps:
                if not await self.kv.renew(key, token, ttl):
                    logger.warning("memory consolidation lost its lock tenant={} user={}", tenant_id, user_id)
                    return
                try:
                    await step(tenant_id, user_id)
                except Exception as exc:  # noqa: BLE001 - counted and retried next scan
                    await self._record_failure(tenant_id, user_id, None, exc, config, now, retry=False)
        finally:
            await self.kv.release(key, token)

    async def _one_session(self, row: MemorySessionCursor, config, now: datetime) -> None:
        ctx = None
        try:
            end_id = await CursorRepository.max_message_id(row.chat_id)
            scene, app_id, app_enabled, app_name, deleted = await session_scene(row.chat_id)
            ctx = None if deleted else await MemoryGate.resolve(row.chat_id, scene, app_enabled, app_id, app_name)
            if ctx is None:
                # Deleted session or memory off: skip these messages for good (AC-41).
                await CursorRepository.finish(row.chat_id, end_id)
                return
            ctx.turn_id = None
            started = await self._clear_marker(ctx)
            result = await self.content_fn(ctx, row, end_id) if end_id > row.watermark_message_id else []
            # The content step may stop early on a very long backlog; it then reports the
            # last message it actually read, and the rest waits for the next run.
            ops, consumed_end = result if isinstance(result, tuple) else (result, end_id)
            if await self._clear_marker(ctx) != started:
                # The user cleared their memory while this run was working on pre-clear
                # messages: drop the results (AC-93); the clear already moved the watermark.
                await CursorRepository.release_running([row.chat_id])
                return
            async with _db.async_session() as s:
                new_items = await self.service.apply_operations(s, ctx, ops)
                await CursorRepository.finish(row.chat_id, consumed_end, session=s)
                if new_items or any(op.get("op") == "pin" for op in ops):
                    await SettingRepository.bump_rev(s, ctx)
                await s.commit()
            await self.service.after_auto_commit(ctx, new_items)
        except Exception as exc:  # noqa: BLE001 - any failure is retried with backoff (AC-45)
            await self._record_failure(row.tenant_id, row.user_id, row, exc, config, now, ctx=ctx)

    async def _clear_marker(self, ctx) -> str | None:
        return await self.kv.get(clear_marker_key(ctx.tenant_id, ctx.user_id))

    async def _record_failure(self, tenant_id, user_id, row, exc, config, now, ctx=None, retry=True):
        from bisheng.memory.domain.ports import MemoryContext

        reason = type(exc).__name__
        if await self._should_log(tenant_id, user_id, reason):
            logger.opt(exception=exc).warning("memory consolidation failed tenant={} user={}", tenant_id, user_id)
        await self.metrics.incr(ctx or MemoryContext(tenant_id=tenant_id, user_id=user_id), m.CONSOLIDATE_FAILED)
        if retry and row is not None:
            delay = min(timedelta(minutes=config.scan_interval_minutes) * (2 ** (row.fail_count + 1)), MAX_BACKOFF)
            await CursorRepository.fail(row.chat_id, now + delay)
