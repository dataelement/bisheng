"""Per-turn records behind operation notices and attribution (design decision 15).

A turn gets a ``turn_id`` when it starts; records hang on it and get the answer's
``message_id`` once the answer is persisted (``bind_turn``). Only the owner can
read them back.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError

from bisheng.memory.domain.models.memory_resident_snapshot import MemoryResidentSnapshot
from bisheng.memory.domain.models.memory_turn_record import KIND_RETRIEVED, KIND_SUMMARY, KIND_WRITE, MemoryTurnRecord
from bisheng.memory.domain.ports import MemoryContext
from bisheng.memory.domain.repositories import _db
from bisheng.memory.domain.repositories.turn_repository import TurnRepository


def _row(ctx: MemoryContext, kind: str, **kw) -> MemoryTurnRecord:
    return MemoryTurnRecord(
        turn_id=ctx.turn_id, chat_id=ctx.chat_id, tenant_id=ctx.tenant_id, user_id=ctx.user_id, kind=kind, **kw
    )


class TurnRecordService:
    @staticmethod
    def empty() -> dict:
        return {"turn_id": None, "writes": [], "retrieved_item_ids": [], "summary": None}

    # ---- writes ---------------------------------------------------------------------
    @classmethod
    async def add_write(cls, session, ctx: MemoryContext, op: str, item_id: str | None, related_item_id=None):
        """Inside the caller's transaction (same commit as the item change)."""
        if not ctx.turn_id:
            return None
        row = _row(ctx, KIND_WRITE, op=op, item_id=item_id, related_item_id=related_item_id)
        session.add(row)
        await session.flush()
        return row

    @classmethod
    async def add_retrieved(cls, ctx: MemoryContext, item_ids: list[str]) -> None:
        if not ctx.turn_id or not item_ids:
            return
        async with _db.async_session() as s:
            rows = await TurnRepository.find(s, ctx, turn_id=ctx.turn_id, kind=KIND_RETRIEVED)
            if rows:
                row = rows[0]
                merged = list(row.item_ids or [])
                merged += [i for i in item_ids if i not in merged]
                row.item_ids = merged
                s.add(row)
            else:
                s.add(_row(ctx, KIND_RETRIEVED, item_ids=list(dict.fromkeys(item_ids))))
            await s.commit()

    @classmethod
    async def add_summary(
        cls,
        ctx: MemoryContext,
        resident_rev: int | None,
        resident_day: str | None,
        scene_class: str | None,
        message_id: int | None = None,
        consolidated: bool = False,
    ) -> None:
        if not ctx.turn_id:
            return
        async with _db.async_session() as s:
            rows = await TurnRepository.find(s, ctx, turn_id=ctx.turn_id, kind=KIND_SUMMARY)
            if rows:
                row = rows[0]
                row.resident_rev, row.resident_day, row.scene_class = resident_rev, resident_day, scene_class
                if message_id is not None:
                    row.message_id = message_id
            else:
                row = _row(
                    ctx,
                    KIND_SUMMARY,
                    resident_rev=resident_rev,
                    resident_day=resident_day,
                    scene_class=scene_class,
                    message_id=message_id,
                    consolidated=consolidated,
                )
            s.add(row)
            await s.commit()

    @classmethod
    async def bind_turn(cls, ctx: MemoryContext, message_id: int | None) -> None:
        if not ctx or not ctx.turn_id or not message_id:
            return
        async with _db.async_session() as s:
            await s.exec(TurnRepository.bind_stmt(ctx, message_id))
            await s.commit()

    @classmethod
    def bind_turn_sync(cls, ctx: MemoryContext, message_id: int | None) -> None:
        """For synchronous persistence paths (daily-mode interrupt, decision 15)."""
        if not ctx or not ctx.turn_id or not message_id:
            return
        with _db.sync_session() as s:
            s.exec(TurnRepository.bind_stmt(ctx, message_id))
            s.commit()

    # ---- reads (owner only) ---------------------------------------------------------
    @staticmethod
    def _assemble(rows) -> dict:
        out = TurnRecordService.empty()
        for r in rows:
            out["turn_id"] = out["turn_id"] or r.turn_id
            if r.kind == KIND_WRITE:
                out["writes"].append(
                    {
                        "record_id": r.id,
                        "op": r.op,
                        "item_id": r.item_id,
                        "related_item_id": r.related_item_id,
                        "undone": bool(r.undone),
                    }
                )
            elif r.kind == KIND_RETRIEVED:
                for i in r.item_ids or []:
                    if i not in out["retrieved_item_ids"]:
                        out["retrieved_item_ids"].append(i)
            elif r.kind == KIND_SUMMARY:
                out["summary"] = {
                    "resident_rev": r.resident_rev,
                    "resident_day": r.resident_day,
                    "scene_class": r.scene_class,
                }
        return out

    @classmethod
    async def get_for_owner(cls, ctx: MemoryContext, *, turn_id: str | None = None, message_id: int | None = None):
        if turn_id is None and message_id is None:
            return cls.empty()
        async with _db.async_session() as s:
            rows = await TurnRepository.find(s, ctx, turn_id=turn_id, message_id=message_id)
        return cls._assemble(rows)

    @staticmethod
    def _flags(rows) -> dict[int, dict]:
        flags: dict[int, dict] = {}
        for r in rows:
            f = flags.setdefault(r.message_id, {"turn_id": r.turn_id, "has_write": False, "has_attribution": False})
            if r.kind == KIND_WRITE:
                f["has_write"] = True
            elif r.kind == KIND_RETRIEVED:
                f["has_attribution"] = True
        return flags

    @classmethod
    async def flags_for_chat(cls, ctx: MemoryContext, chat_id: str) -> dict[int, dict]:
        async with _db.async_session() as s:
            rows = list((await s.exec(TurnRepository.find_by_chat_stmt(ctx, chat_id))).all())
        return cls._flags(rows)

    @classmethod
    def flags_for_chat_sync(cls, ctx: MemoryContext, chat_id: str) -> dict[int, dict]:
        with _db.sync_session() as s:
            rows = list(s.exec(TurnRepository.find_by_chat_stmt(ctx, chat_id)).all())
        return cls._flags(rows)

    # ---- resident snapshots ---------------------------------------------------------
    @classmethod
    async def save_snapshot(cls, ctx, rev: int, day: str, scene_class: str, item_ids: list[str]) -> None:
        async with _db.async_session() as s:
            if await TurnRepository.get_snapshot(s, ctx, rev, day, scene_class) is not None:
                return
        try:
            async with _db.async_session() as s:
                s.add(
                    MemoryResidentSnapshot(
                        tenant_id=ctx.tenant_id,
                        user_id=ctx.user_id,
                        rev=rev,
                        day=day,
                        scene_class=scene_class,
                        item_ids=list(item_ids),
                    )
                )
                await s.commit()
        except IntegrityError:
            # Another node wrote the same (rev, day) snapshot first; content is identical.
            pass

    @classmethod
    async def get_snapshot(cls, ctx, rev: int, day: str, scene_class: str) -> list[str]:
        async with _db.async_session() as s:
            row = await TurnRepository.get_snapshot(s, ctx, rev, day, scene_class)
        return list(row.item_ids) if row else []

    # ---- lifecycle ------------------------------------------------------------------
    @classmethod
    async def delete_user(cls, ctx: MemoryContext, session=None) -> None:
        if session is not None:
            await TurnRepository.delete_user(session, ctx)
            return
        async with _db.async_session() as s:
            await TurnRepository.delete_user(s, ctx)
            await s.commit()

    @classmethod
    async def cleanup_orphans(cls, older_than: timedelta = timedelta(days=1)) -> int:
        async with _db.async_session() as s:
            n = await TurnRepository.delete_orphans(s, datetime.now() - older_than)
            await s.commit()
        return n
