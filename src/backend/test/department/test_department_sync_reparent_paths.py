"""Database regression tests for sync-driven department subtree moves."""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

import bisheng.database.models.department as department_module
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.department import Department, DepartmentDao


@pytest.mark.asyncio
async def test_sync_upsert_rewrites_descendant_paths(monkeypatch: pytest.MonkeyPatch):
    engine = create_async_engine("sqlite+aiosqlite://", future=True)
    async with engine.begin() as connection:
        await connection.run_sync(Department.__table__.create)

    @asynccontextmanager
    async def _session_factory():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr(department_module, "get_async_db_session", _session_factory)

    with bypass_tenant_filter():
        async with _session_factory() as session:
            default_root = Department(
                dept_id="BS@root",
                name="默认组织",
                tenant_id=1,
                parent_id=None,
                path="/1/",
                source="local",
                external_id="BS@root",
            )
            session.add(default_root)
            await session.commit()
            await session.refresh(default_root)
            default_root.path = f"/{default_root.id}/"

            synced_root = Department(
                dept_id="SG@root",
                name="第三方根部门",
                tenant_id=1,
                parent_id=None,
                path="",
                source="sg",
                external_id="root",
            )
            session.add(synced_root)
            await session.commit()
            await session.refresh(synced_root)
            synced_root.path = f"/{synced_root.id}/"

            child = Department(
                dept_id="SG@child",
                name="下级部门",
                tenant_id=1,
                parent_id=synced_root.id,
                path=f"/{synced_root.id}/",
                source="sg",
                external_id="child",
            )
            session.add(child)
            await session.commit()
            await session.refresh(child)
            child.path = f"/{synced_root.id}/{child.id}/"
            session.add_all([default_root, synced_root, child])
            await session.commit()

        moved = await DepartmentDao.aupsert_by_external_id(
            source="sg",
            external_id="root",
            name="第三方根部门",
            parent_id=int(default_root.id),
            path=default_root.path,
            sort_order=0,
            last_sync_ts=100,
            tenant_id=1,
        )

        async with _session_factory() as session:
            refreshed_child = (
                await session.exec(
                    select(Department).where(Department.id == child.id),
                )
            ).one()

    assert moved.parent_id == default_root.id
    assert moved.path == f"/{default_root.id}/{synced_root.id}/"
    assert refreshed_child.path == f"/{default_root.id}/{synced_root.id}/{child.id}/"

    await engine.dispose()
