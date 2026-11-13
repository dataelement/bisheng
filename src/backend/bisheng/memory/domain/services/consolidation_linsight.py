"""Consolidation of deep-research rounds (design decision 7, R8, P-01).

Deep research is consolidated per round, not by message watermark: the
watermark consolidation skips ``category='task'`` rows. Every round has one
summary row (``scene_class='linsight'``) bound to its task message row. This
step, run by the per-user ``Consolidator`` under the user lock, takes the user's
summary rows that are not consolidated yet:

- ended rounds whose session version is final are read through the
  deep-research module (question + result), turned into operations by the same
  content function as the daily path, applied, and flagged in one transaction;
- rounds not ended (running, parked on ask_user) wait, and are abandoned after
  24 hours (``op='abandoned'``, flagged, never tried again);
- ``/workbench/continue`` rounds were flagged at start (P-01 option C) and are
  never selected.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from loguru import logger
from sqlalchemy import update
from sqlmodel import select

from bisheng.memory.domain.models.memory_turn_record import KIND_SUMMARY, MemoryTurnRecord
from bisheng.memory.domain.ports import SCENE_LINSIGHT
from bisheng.memory.domain.repositories import _db
from bisheng.memory.domain.repositories.setting_repository import SettingRepository
from bisheng.memory.domain.services.app_switch import session_scene
from bisheng.memory.domain.services.consolidation_content import MAX_MESSAGE_CHARS, MAX_TOTAL_CHARS
from bisheng.memory.domain.services.gate import MemoryGate
from bisheng.memory.domain.services.resident import SCENE_CLASS_LINSIGHT

R = MemoryTurnRecord
ABANDON_AFTER = timedelta(hours=24)
OP_ABANDONED = "abandoned"


async def _default_reader(chat_id: str, message_id: int):
    from bisheng.linsight.domain.services.memory_turns import read_round_for_memory

    return await read_round_for_memory(chat_id, message_id)


def _flag_stmt(row: R, op: str | None = None):
    values = {"consolidated": True}
    if op:
        values["op"] = op
    return (
        update(R)
        .where(R.id == row.id, R.tenant_id == row.tenant_id, R.user_id == row.user_id, R.consolidated == False)  # noqa: E712 - DM8 rejects IS 1 / IS 0
        .values(**values)
    )


class LinsightRoundConsolidation:
    """``Consolidator`` extra step: ``await step(tenant_id, user_id)``."""

    def __init__(self, service, content, reader=None, abandon_after: timedelta = ABANDON_AFTER):
        self.service = service
        self.content = content
        self.reader = reader or _default_reader
        self.abandon_after = abandon_after

    async def _pending(self, tenant_id: int, user_id: int) -> list[R]:
        stmt = (
            select(R)
            .where(
                R.tenant_id == tenant_id,
                R.user_id == user_id,
                R.kind == KIND_SUMMARY,
                R.scene_class == SCENE_CLASS_LINSIGHT,
                R.consolidated == False,  # noqa: E712 - DM8 rejects IS 1 / IS 0
            )
            .order_by(R.id.asc())
        )
        async with _db.async_session() as s:
            return list((await s.exec(stmt)).all())

    async def _flag(self, row: R, op: str | None = None) -> None:
        async with _db.async_session() as s:
            await s.exec(_flag_stmt(row, op))
            await s.commit()

    async def __call__(self, tenant_id: int, user_id: int, now: datetime | None = None) -> None:
        now = now or datetime.now()
        first_error: Exception | None = None
        for row in await self._pending(tenant_id, user_id):
            try:
                await self._one(row, now)
            except Exception as exc:
                logger.opt(exception=exc).warning("memory: deep-research round consolidation failed id={}", row.id)
                first_error = first_error or exc
        if first_error is not None:
            raise first_error

    async def _one(self, row: R, now: datetime) -> None:
        if not row.ended:
            if row.create_time is not None and row.create_time < now - self.abandon_after:
                await self._flag(row, OP_ABANDONED)
            return
        if not row.message_id or not row.chat_id:
            await self._flag(row, OP_ABANDONED)
            return
        _scene, _app_id, _enabled, _name, deleted = await session_scene(row.chat_id)
        ctx = None if deleted else await MemoryGate.resolve(row.chat_id, SCENE_LINSIGHT)
        if ctx is None or ctx.tenant_id != row.tenant_id or ctx.user_id != row.user_id:
            # Deleted conversation, memory off or registration changed: skip this round for good (AC-41).
            await self._flag(row)
            return
        ctx.turn_id = None
        found = await self.reader(row.chat_id, row.message_id)
        if found is None:
            await self._flag(row, OP_ABANDONED)
            return
        if not found.get("finished"):
            return
        question = str(found.get("question") or "").strip()[:MAX_MESSAGE_CHARS]
        answer = str(found.get("answer") or "").strip()[: max(0, MAX_TOTAL_CHARS - len(question))]
        messages = [(role, text) for role, text in (("用户", question), ("系统", answer)) if text]
        ops = await self.content.from_messages(ctx, messages) if messages else []
        async with _db.async_session() as s:
            new_items = await self.service.apply_operations(s, ctx, ops)
            await s.exec(_flag_stmt(row))
            if new_items or any(op.get("op") == "pin" for op in ops):
                await SettingRepository.bump_rev(s, ctx)
            await s.commit()
        await self.service.after_auto_commit(ctx, new_items)
