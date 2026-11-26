"""Data access for memory_user_setting (switch, timezone, rev). Decisions 8, 9, 13."""

from __future__ import annotations

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from bisheng.memory.domain.models.memory_user_setting import MemoryUserSetting
from bisheng.memory.domain.ports import MemoryContext
from bisheng.memory.domain.repositories import _db


def _scope(ctx: MemoryContext):
    if ctx.tenant_id is None or ctx.user_id is None:
        raise ValueError("memory repository requires tenant_id and user_id")
    return (MemoryUserSetting.tenant_id == ctx.tenant_id, MemoryUserSetting.user_id == ctx.user_id)


class SettingRepository:
    @classmethod
    async def get(cls, ctx: MemoryContext, session=None) -> MemoryUserSetting | None:
        stmt = select(MemoryUserSetting).where(*_scope(ctx))
        if session is not None:
            return (await session.exec(stmt)).first()
        async with _db.async_session() as s:
            return (await s.exec(stmt)).first()

    @classmethod
    def get_sync(cls, ctx: MemoryContext) -> MemoryUserSetting | None:
        with _db.sync_session() as s:
            return s.exec(select(MemoryUserSetting).where(*_scope(ctx))).first()

    @classmethod
    async def ensure(cls, ctx: MemoryContext) -> MemoryUserSetting:
        """Create the row on first need; a concurrent creator wins and we re-read."""
        row = await cls.get(ctx)
        if row is not None:
            return row
        try:
            async with _db.async_session() as s:
                s.add(MemoryUserSetting(tenant_id=ctx.tenant_id, user_id=ctx.user_id, enabled=True, rev=0))
                await s.commit()
        except IntegrityError:
            # Another request created the row between our read and insert.
            pass
        return await cls.get(ctx)

    @classmethod
    async def bump_rev(cls, session, ctx: MemoryContext) -> None:
        """rev += 1 inside the caller's transaction; creates the row when missing."""
        stmt = update(MemoryUserSetting).where(*_scope(ctx)).values(rev=MemoryUserSetting.rev + 1)
        if (await session.exec(stmt)).rowcount == 0:
            session.add(MemoryUserSetting(tenant_id=ctx.tenant_id, user_id=ctx.user_id, enabled=True, rev=1))
            await session.flush()

    @classmethod
    async def set_enabled(cls, ctx: MemoryContext, enabled: bool) -> MemoryUserSetting:
        await cls.ensure(ctx)
        async with _db.async_session() as s:
            await s.exec(update(MemoryUserSetting).where(*_scope(ctx)).values(enabled=enabled))
            await s.commit()
        return await cls.get(ctx)

    @classmethod
    async def set_timezone(cls, ctx: MemoryContext, timezone: str) -> bool:
        """Write only when the value changed. Returns whether a write happened."""
        row = await cls.ensure(ctx)
        if row.timezone == timezone:
            return False
        async with _db.async_session() as s:
            await s.exec(update(MemoryUserSetting).where(*_scope(ctx)).values(timezone=timezone))
            await s.commit()
        return True
