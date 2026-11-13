"""Data access for memory_session_cursor (decisions 6, 7).

Every update is a column-wise conditional UPDATE; no read-modify-write. The
watermark only moves forward (``max(current, new)``).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import case, func, or_, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from bisheng.memory.domain.models.memory_session_cursor import (
    STATE_IDLE,
    STATE_PENDING,
    STATE_RUNNING,
    MemorySessionCursor,
)
from bisheng.memory.domain.repositories import _db

C = MemorySessionCursor


def _greatest(column, value: int):
    """Portable ``GREATEST(column, value)`` (SQLite has no GREATEST)."""
    return case((column < value, value), else_=column)


class CursorRepository:
    # ---- reads -----------------------------------------------------------------
    @classmethod
    async def get(cls, chat_id: str) -> MemorySessionCursor | None:
        async with _db.async_session() as s:
            return await s.get(C, chat_id)

    @classmethod
    def get_sync(cls, chat_id: str) -> MemorySessionCursor | None:
        with _db.sync_session() as s:
            return s.get(C, chat_id)

    # ---- registration --------------------------------------------------------------
    @classmethod
    async def create(cls, row: MemorySessionCursor) -> bool:
        """Insert; returns False when a concurrent request created it first."""
        try:
            async with _db.async_session() as s:
                s.add(row)
                await s.commit()
            return True
        except IntegrityError:
            return False

    @classmethod
    async def set_timezone(cls, chat_id: str, tenant_id: int, user_id: int, timezone: str | None) -> None:
        async with _db.async_session() as s:
            await s.exec(
                update(C)
                .where(C.chat_id == chat_id, C.tenant_id == tenant_id, C.user_id == user_id)
                .where(or_(C.timezone.is_(None), C.timezone != timezone))
                .values(timezone=timezone)
            )
            await s.commit()

    @classmethod
    async def mark_ineligible(cls, chat_id: str) -> None:
        async with _db.async_session() as s:
            await s.exec(update(C).where(C.chat_id == chat_id).values(eligible=False))
            await s.commit()

    # ---- turn end (decision 7) --------------------------------------------------------
    @classmethod
    def _end_turn_stmt(cls, chat_id: str, last_message_id: int, enabled: bool, now: datetime):
        last = int(last_message_id or 0)
        values = {"last_message_id": _greatest(C.last_message_id, last), "last_activity_at": now}
        if enabled:
            values["state"] = case((C.state == STATE_RUNNING, STATE_RUNNING), else_=STATE_PENDING)
        else:
            values["watermark_message_id"] = _greatest(C.watermark_message_id, last)
        return update(C).where(C.chat_id == chat_id, C.eligible.is_(True)).values(**values)

    @classmethod
    async def end_turn(cls, chat_id: str, last_message_id: int, enabled: bool, now: datetime) -> int:
        async with _db.async_session() as s:
            n = (await s.exec(cls._end_turn_stmt(chat_id, last_message_id, enabled, now))).rowcount
            await s.commit()
        return n

    @classmethod
    def end_turn_sync(cls, chat_id: str, last_message_id: int, enabled: bool, now: datetime) -> int:
        with _db.sync_session() as s:
            n = s.exec(cls._end_turn_stmt(chat_id, last_message_id, enabled, now)).rowcount
            s.commit()
        return n

    # ---- consolidation scheduling -----------------------------------------------------
    @classmethod
    def _due_filter(cls, now: datetime, quiet: timedelta, lock_ttl: timedelta):
        pending_due = (
            (C.state == STATE_PENDING)
            & (C.last_activity_at <= now - quiet)
            & or_(C.next_run_at.is_(None), C.next_run_at <= now)
        )
        stale_running = (C.state == STATE_RUNNING) & (C.locked_at <= now - lock_ttl)
        return C.eligible.is_(True) & or_(pending_due, stale_running)

    @classmethod
    async def list_due_users(cls, now: datetime, quiet: timedelta, lock_ttl: timedelta) -> list[tuple[int, int]]:
        """(tenant_id, user_id) pairs that have at least one due session. Cross-tenant."""
        stmt = select(C.tenant_id, C.user_id).where(cls._due_filter(now, quiet, lock_ttl)).distinct()
        async with _db.async_session() as s:
            return [(int(t), int(u)) for t, u in (await s.exec(stmt)).all()]

    @classmethod
    async def list_due_for_user(
        cls, tenant_id: int, user_id: int, now: datetime, quiet: timedelta, lock_ttl: timedelta
    ) -> list[MemorySessionCursor]:
        stmt = (
            select(C)
            .where(C.tenant_id == tenant_id, C.user_id == user_id)
            .where(cls._due_filter(now, quiet, lock_ttl))
            .order_by(C.last_activity_at.asc())
        )
        async with _db.async_session() as s:
            return list((await s.exec(stmt)).all())

    @classmethod
    async def mark_running(cls, chat_ids: list[str], now: datetime) -> None:
        if not chat_ids:
            return
        async with _db.async_session() as s:
            await s.exec(update(C).where(C.chat_id.in_(chat_ids)).values(state=STATE_RUNNING, locked_at=now))
            await s.commit()

    @classmethod
    def finish_stmt(cls, chat_id: str, end_id: int):
        """Advance watermark; go idle only when no newer message arrived meanwhile."""
        return (
            update(C)
            .where(C.chat_id == chat_id)
            .values(
                watermark_message_id=_greatest(C.watermark_message_id, end_id),
                state=case((C.last_message_id <= end_id, STATE_IDLE), else_=STATE_PENDING),
                fail_count=0,
                next_run_at=None,
                locked_at=None,
            )
        )

    @classmethod
    async def finish(cls, chat_id: str, end_id: int, session=None) -> None:
        if session is not None:
            await session.exec(cls.finish_stmt(chat_id, end_id))
            return
        async with _db.async_session() as s:
            await s.exec(cls.finish_stmt(chat_id, end_id))
            await s.commit()

    @classmethod
    async def fail(cls, chat_id: str, next_run_at: datetime) -> None:
        async with _db.async_session() as s:
            await s.exec(
                update(C)
                .where(C.chat_id == chat_id)
                .values(state=STATE_PENDING, fail_count=C.fail_count + 1, next_run_at=next_run_at, locked_at=None)
            )
            await s.commit()

    @classmethod
    async def release_running(cls, chat_ids: list[str]) -> None:
        """Put rows we marked running but did not process back to pending."""
        if not chat_ids:
            return
        async with _db.async_session() as s:
            await s.exec(
                update(C).where(C.chat_id.in_(chat_ids), C.state == STATE_RUNNING).values(state=STATE_PENDING)
            )
            await s.commit()

    @classmethod
    async def advance_all_for_user(cls, tenant_id: int, user_id: int) -> None:
        """Clear: push every watermark of this user to the latest seen message (decision 7)."""
        async with _db.async_session() as s:
            await s.exec(
                update(C)
                .where(C.tenant_id == tenant_id, C.user_id == user_id)
                .values(
                    watermark_message_id=_greatest(C.watermark_message_id, C.last_message_id),
                    state=STATE_IDLE,
                )
            )
            await s.commit()

    @classmethod
    async def max_message_id(cls, chat_id: str) -> int:
        from bisheng.database.models.message import ChatMessage

        async with _db.async_session() as s:
            value = (await s.exec(select(func.max(ChatMessage.id)).where(ChatMessage.chat_id == chat_id))).first()
        return int(value or 0)

    @classmethod
    def max_message_id_sync(cls, chat_id: str) -> int:
        from bisheng.database.models.message import ChatMessage

        with _db.sync_session() as s:
            value = s.exec(select(func.max(ChatMessage.id)).where(ChatMessage.chat_id == chat_id)).first()
        return int(value or 0)
