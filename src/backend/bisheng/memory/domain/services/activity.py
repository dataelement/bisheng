"""MemoryActivity: one call per finished turn (design decision 7).

``end_turn(enabled=True)`` marks the session pending (consolidation after the
quiet period); ``end_turn(enabled=False)`` advances the watermark past this turn
so it is never consolidated (AC-40, AC-41). All updates are conditional,
column-wise and monotonic; unregistered sessions are a no-op.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from bisheng.memory.domain.repositories.cursor_repository import CursorRepository


class MemoryActivity:
    @classmethod
    async def end_turn(cls, chat_id: str | None, last_message_id: int | None, enabled: bool, now=None) -> None:
        if not chat_id:
            return
        if last_message_id is None:
            last_message_id = await CursorRepository.max_message_id(chat_id)
        await CursorRepository.end_turn(chat_id, last_message_id, enabled, now or datetime.now())

    @classmethod
    def end_turn_sync(cls, chat_id: str | None, last_message_id: int | None, enabled: bool, now=None) -> None:
        if not chat_id:
            return
        if last_message_id is None:
            last_message_id = CursorRepository.max_message_id_sync(chat_id)
        CursorRepository.end_turn_sync(chat_id, last_message_id, enabled, now or datetime.now())

    @classmethod
    async def due_users(cls, now: datetime, quiet: timedelta, lock_ttl: timedelta) -> list[tuple[int, int]]:
        return await CursorRepository.list_due_users(now, quiet, lock_ttl)
