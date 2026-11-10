"""Tenant-scoped reads for Desktop hosted applications."""

from sqlmodel import select

from bisheng.core.database import get_async_db_session
from bisheng.database.models.app import App, AppDao


class DesktopAppRepository:
    async def get(self, app_id):
        async with get_async_db_session() as session:
            return await AppDao.aget(session, app_id)

    async def page(self, *, after=None, limit=100):
        query = select(App).order_by(App.id).limit(limit + 1)
        if after:
            query = query.where(App.id > after)
        async with get_async_db_session() as session:
            rows = list((await session.exec(query)).all())
        return rows[:limit], str(rows[limit - 1].id) if len(rows) > limit else None
