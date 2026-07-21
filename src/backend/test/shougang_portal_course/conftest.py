from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.shougang_portal_course.domain.models.portal_course import (
    PortalCourse,
    PortalCourseMediaCleanup,
    PortalCourseVideo,
    PortalCourseVideoProgress,
)


@pytest.fixture()
async def course_session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [
        PortalCourse.__table__,
        PortalCourseVideo.__table__,
        PortalCourseVideoProgress.__table__,
        PortalCourseMediaCleanup.__table__,
    ]
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: PortalCourse.metadata.create_all(sync, tables=tables))
    async with AsyncSession(bind=engine, expire_on_commit=False) as session:
        yield session
    await engine.dispose()
