"""Data access for memory_turn_record and memory_resident_snapshot (decision 15).

All reads and writes carry tenant + user of the owner, so a non-owner never sees
another user's turn records (AC-08, AC-09).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, update
from sqlmodel import select

from bisheng.memory.domain.models.memory_resident_snapshot import MemoryResidentSnapshot
from bisheng.memory.domain.models.memory_turn_record import MemoryTurnRecord
from bisheng.memory.domain.ports import MemoryContext

R = MemoryTurnRecord
S = MemoryResidentSnapshot


def _owner(ctx: MemoryContext, model=R):
    return (model.tenant_id == ctx.tenant_id, model.user_id == ctx.user_id)


class TurnRepository:
    @classmethod
    async def find(cls, session, ctx: MemoryContext, *, turn_id=None, message_id=None, kind=None) -> list[R]:
        stmt = select(R).where(*_owner(ctx))
        if turn_id is not None:
            stmt = stmt.where(R.turn_id == turn_id)
        if message_id is not None:
            stmt = stmt.where(R.message_id == message_id)
        if kind is not None:
            stmt = stmt.where(R.kind == kind)
        return list((await session.exec(stmt.order_by(R.id.asc()))).all())

    @classmethod
    def bind_stmt(cls, ctx: MemoryContext, message_id: int):
        return (
            update(R)
            .where(*_owner(ctx), R.turn_id == ctx.turn_id, R.message_id.is_(None))
            .values(message_id=int(message_id))
        )

    @classmethod
    def find_by_chat_stmt(cls, ctx: MemoryContext, chat_id: str):
        return select(R).where(*_owner(ctx), R.chat_id == chat_id, R.message_id.is_not(None)).order_by(R.id.asc())

    @classmethod
    async def delete_user(cls, session, ctx: MemoryContext) -> None:
        await session.exec(delete(R).where(*_owner(ctx)))
        await session.exec(delete(S).where(*_owner(ctx, S)))

    @classmethod
    async def get_snapshot(cls, session, ctx: MemoryContext, rev: int, day: str, scene_class: str) -> S | None:
        stmt = select(S).where(*_owner(ctx, S), S.rev == rev, S.day == day, S.scene_class == scene_class)
        return (await session.exec(stmt)).first()

    @classmethod
    async def delete_orphans(cls, session, before: datetime) -> int:
        """Cross-tenant maintenance: records never bound to a message (process crash)."""
        stmt = delete(R).where(R.message_id.is_(None), R.create_time < before)
        return (await session.exec(stmt)).rowcount
