"""Data access for memory_item. Every method filters by tenant AND user (decision 9).

Methods take an open session so that item changes, the ``rev`` bump and turn
records commit in one transaction; the caller owns commit/rollback.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, func, update
from sqlmodel import select

from bisheng.memory.domain.models.memory_item import INDEX_PENDING, STATUS_ACTIVE, MemoryItem
from bisheng.memory.domain.ports import MemoryContext


def _scope(ctx: MemoryContext):
    if ctx.tenant_id is None or ctx.user_id is None:
        raise ValueError("memory repository requires tenant_id and user_id")
    return (MemoryItem.tenant_id == ctx.tenant_id, MemoryItem.user_id == ctx.user_id)


class ItemRepository:
    @classmethod
    async def insert(cls, session, ctx: MemoryContext, item: MemoryItem) -> MemoryItem:
        item.tenant_id = ctx.tenant_id
        item.user_id = ctx.user_id
        session.add(item)
        await session.flush()
        return item

    @classmethod
    async def get(cls, session, ctx: MemoryContext, item_id: str) -> MemoryItem | None:
        stmt = select(MemoryItem).where(MemoryItem.id == item_id, *_scope(ctx))
        return (await session.exec(stmt)).first()

    @classmethod
    async def get_active(cls, session, ctx: MemoryContext, item_id: str) -> MemoryItem | None:
        item = await cls.get(session, ctx, item_id)
        return item if item is not None and item.status == STATUS_ACTIVE else None

    @classmethod
    async def list_active(
        cls,
        session,
        ctx: MemoryContext,
        types: tuple[str, ...] | None = None,
        pinned: bool | None = None,
    ) -> list[MemoryItem]:
        stmt = select(MemoryItem).where(*_scope(ctx), MemoryItem.status == STATUS_ACTIVE)
        if types:
            stmt = stmt.where(MemoryItem.type.in_(types))
        if pinned is not None:
            stmt = stmt.where(MemoryItem.pinned == pinned)
        stmt = stmt.order_by(MemoryItem.recorded_at.desc(), MemoryItem.id.desc())
        return list((await session.exec(stmt)).all())

    @classmethod
    async def list_resident(cls, session, ctx: MemoryContext, types: tuple[str, ...]) -> list[MemoryItem]:
        stmt = (
            select(MemoryItem)
            .where(*_scope(ctx), MemoryItem.status == STATUS_ACTIVE, MemoryItem.pinned.is_(True))
            .where(MemoryItem.type.in_(types))
            .order_by(MemoryItem.pin_order.asc(), MemoryItem.recorded_at.desc(), MemoryItem.id.asc())
        )
        return list((await session.exec(stmt)).all())

    @classmethod
    async def list_by_ids(
        cls, session, ctx: MemoryContext, item_ids: list[str], active_only: bool = True
    ) -> list[MemoryItem]:
        if not item_ids:
            return []
        stmt = select(MemoryItem).where(*_scope(ctx), MemoryItem.id.in_(item_ids))
        if active_only:
            stmt = stmt.where(MemoryItem.status == STATUS_ACTIVE)
        return list((await session.exec(stmt)).all())

    @classmethod
    async def list_pending_index(cls, session, ctx: MemoryContext, limit: int = 20) -> list[MemoryItem]:
        stmt = (
            select(MemoryItem)
            .where(*_scope(ctx), MemoryItem.status == STATUS_ACTIVE, MemoryItem.index_state == INDEX_PENDING)
            .order_by(MemoryItem.recorded_at.desc(), MemoryItem.id.desc())
            .limit(limit)
        )
        return list((await session.exec(stmt)).all())

    @classmethod
    async def list_all_ids(cls, session, ctx: MemoryContext) -> list[str]:
        return list((await session.exec(select(MemoryItem.id).where(*_scope(ctx)))).all())

    @classmethod
    async def list_detail_keys(cls, session, ctx: MemoryContext) -> list[str]:
        stmt = select(MemoryItem.detail_object_key).where(*_scope(ctx), MemoryItem.detail_object_key.is_not(None))
        return [k for k in (await session.exec(stmt)).all() if k]

    @classmethod
    async def update_status(
        cls,
        session,
        ctx: MemoryContext,
        item_id: str,
        from_status: str,
        to_status: str,
        superseded_by: str | None = None,
        clear_superseded_by: bool = False,
    ) -> int:
        """Conditional state change; rowcount 0 means the target is gone or changed."""
        values = {"status": to_status}
        if superseded_by is not None:
            values["superseded_by"] = superseded_by
        if clear_superseded_by:
            values["superseded_by"] = None
        stmt = (
            update(MemoryItem)
            .where(MemoryItem.id == item_id, *_scope(ctx), MemoryItem.status == from_status)
            .values(**values)
        )
        return (await session.exec(stmt)).rowcount

    @classmethod
    async def update_fields(cls, session, ctx: MemoryContext, item_ids: list[str], **values) -> int:
        if not item_ids:
            return 0
        stmt = update(MemoryItem).where(MemoryItem.id.in_(item_ids), *_scope(ctx)).values(**values)
        return (await session.exec(stmt)).rowcount

    @classmethod
    async def min_pin_order(cls, session, ctx: MemoryContext) -> int:
        stmt = select(func.min(MemoryItem.pin_order)).where(
            *_scope(ctx), MemoryItem.status == STATUS_ACTIVE, MemoryItem.pinned.is_(True)
        )
        value = (await session.exec(stmt)).first()
        return int(value) if value is not None else 0

    @classmethod
    async def max_pin_order(cls, session, ctx: MemoryContext) -> int:
        stmt = select(func.max(MemoryItem.pin_order)).where(
            *_scope(ctx), MemoryItem.status == STATUS_ACTIVE, MemoryItem.pinned.is_(True)
        )
        value = (await session.exec(stmt)).first()
        return int(value) if value is not None else 0

    @classmethod
    async def touch_read(cls, session, ctx: MemoryContext, item_ids: list[str], column: str, at: datetime) -> int:
        return await cls.update_fields(session, ctx, item_ids, **{column: at})

    @classmethod
    async def delete_all(cls, session, ctx: MemoryContext) -> int:
        """Hard delete of all rows of this user in this tenant (clear, AC-93)."""
        return (await session.exec(delete(MemoryItem).where(*_scope(ctx)))).rowcount
