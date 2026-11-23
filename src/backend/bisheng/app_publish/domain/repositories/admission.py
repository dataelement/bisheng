"""Serialize package admission across API processes using the application row."""

from contextlib import asynccontextmanager

from sqlmodel import select

from bisheng.app_publish.domain.models.app_deployment import AppDeploymentDao
from bisheng.core.database import get_async_db_session
from bisheng.database.models.app import App


class AdmissionTransaction:
    def __init__(self, session):
        self._session = session

    async def insert(self, deployment):
        await AppDeploymentDao.acreate(self._session, deployment)


class AdmissionRepository:
    @staticmethod
    @asynccontextmanager
    async def locked(app_id):
        async with get_async_db_session() as session:
            # The row lock is the point: concurrent submissions for one app queue here.
            await session.exec(select(App).where(App.id == app_id).with_for_update())
            yield AdmissionTransaction(session)
            await session.commit()
