"""Deep-research rounds on the turn-record table (design decision 15, R8).

One deep-research round = one summary row (``scene_class='linsight'``) bound to
the round's task message row. The worker opens it at round start, an ask_user
resume finds it again by the task message id, and the round end sets ``ended``
so the round consolidation (``consolidation_linsight``) knows the round's
question and result are final. Every statement filters by the owner.
"""

from __future__ import annotations

from sqlalchemy import update
from sqlmodel import select

from bisheng.memory.domain.models.memory_turn_record import KIND_SUMMARY, MemoryTurnRecord
from bisheng.memory.domain.ports import MemoryContext
from bisheng.memory.domain.repositories import _db
from bisheng.memory.domain.services.resident import SCENE_CLASS_LINSIGHT

R = MemoryTurnRecord


def _owner(ctx: MemoryContext):
    return (R.tenant_id == ctx.tenant_id, R.user_id == ctx.user_id)


class LinsightTurnService:
    @classmethod
    async def open_round_turn_id(cls, ctx: MemoryContext, message_id: int | None) -> str | None:
        """Turn id of the newest round on this task message that has not ended."""
        if not message_id:
            return None
        stmt = (
            select(R.turn_id)
            .where(
                *_owner(ctx),
                R.chat_id == ctx.chat_id,
                R.message_id == int(message_id),
                R.kind == KIND_SUMMARY,
                R.scene_class == SCENE_CLASS_LINSIGHT,
                R.ended.is_(False),
            )
            .order_by(R.id.desc())
        )
        async with _db.async_session() as s:
            return (await s.exec(stmt)).first()

    @classmethod
    async def mark_ended(cls, ctx: MemoryContext) -> None:
        if not ctx or not ctx.turn_id:
            return
        stmt = update(R).where(*_owner(ctx), R.turn_id == ctx.turn_id, R.kind == KIND_SUMMARY).values(ended=True)
        async with _db.async_session() as s:
            await s.exec(stmt)
            await s.commit()
