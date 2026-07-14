"""Tests for the root-department migration maintenance script."""

from __future__ import annotations

from argparse import Namespace
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.department import Department
from bisheng.database.models.tenant import Tenant
from scripts import migrate_root_departments_under_default_org as script


def _plan() -> script.MigrationPlan:
    return script.MigrationPlan(
        tenant_id=1,
        default_root_id=1,
        default_root_dept_id="BS@root",
        default_root_name="默认组织",
        default_root_path="/1/",
        moves=(
            script.RootDepartmentMove(
                department_id=10,
                dept_id="SG@D1",
                name="第三方根部门",
                source="sg",
                status="active",
                old_path="/10/",
                new_path="/1/10/",
            ),
        ),
    )


def test_normalized_path_rejects_unsafe_values():
    for value in ("", "1/", "/1"):
        with pytest.raises(script.PreflightError):
            script._normalized_path(value, label="test")

    assert script._normalized_path("/1/", label="test") == "/1/"


@pytest.mark.asyncio
async def test_dry_run_never_calls_apply(capsys):
    with (
        patch.object(script, "build_plan", AsyncMock(return_value=_plan())),
        patch.object(script, "apply_plan", AsyncMock()) as apply_plan,
    ):
        assert await script.run(Namespace(apply=False)) == 0

    apply_plan.assert_not_awaited()
    output = capsys.readouterr().out
    assert '"mode": "dry-run"' in output
    assert "Dry-run only" in output


@pytest.mark.asyncio
async def test_apply_uses_the_freshly_built_plan():
    plan = _plan()
    with (
        patch.object(script, "build_plan", AsyncMock(return_value=plan)),
        patch.object(
            script,
            "apply_plan",
            AsyncMock(
                return_value={
                    "moved_departments": 1,
                    "openfga_operations_submitted": 1,
                },
            ),
        ) as apply_plan,
    ):
        assert await script.run(Namespace(apply=True)) == 0

    apply_plan.assert_awaited_once_with(plan)


@pytest.mark.asyncio
async def test_apply_moves_root_and_rewrites_its_subtree(monkeypatch: pytest.MonkeyPatch):
    engine = create_async_engine("sqlite+aiosqlite://", future=True)
    async with engine.begin() as connection:
        await connection.run_sync(Tenant.__table__.create)
        await connection.run_sync(Department.__table__.create)

    @asynccontextmanager
    async def _session_factory():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr(script, "get_async_db_session", _session_factory)

    with bypass_tenant_filter():
        async with _session_factory() as session:
            tenant = Tenant(
                id=1,
                tenant_code="default",
                tenant_name="Default",
                root_dept_id=None,
            )
            session.add(tenant)
            await session.commit()

            default_root = Department(
                dept_id="BS@root",
                name="默认组织",
                tenant_id=1,
                parent_id=None,
                path="",
                source="local",
            )
            session.add(default_root)
            await session.commit()
            await session.refresh(default_root)
            default_root.path = f"/{default_root.id}/"
            tenant.root_dept_id = int(default_root.id)

            other_root = Department(
                dept_id="SG@root",
                name="第三方根部门",
                tenant_id=1,
                parent_id=None,
                path="",
                source="sg",
                external_id="root",
            )
            session.add(other_root)
            await session.commit()
            await session.refresh(other_root)
            other_root.path = f"/{other_root.id}/"

            child = Department(
                dept_id="SG@child",
                name="下级部门",
                tenant_id=1,
                parent_id=other_root.id,
                path=f"/{other_root.id}/",
                source="sg",
                external_id="child",
            )
            session.add(child)
            await session.commit()
            await session.refresh(child)
            child.path = f"/{other_root.id}/{child.id}/"
            session.add_all([tenant, default_root, other_root, child])
            await session.commit()

        plan = await script.build_plan()
        with patch.object(
            script.DepartmentChangeHandler,
            "execute_async",
            AsyncMock(),
        ) as execute_async:
            result = await script.apply_plan(plan)

        async with _session_factory() as session:
            moved_root = (
                await session.exec(
                    select(Department).where(Department.id == other_root.id),
                )
            ).one()
            moved_child = (
                await session.exec(
                    select(Department).where(Department.id == child.id),
                )
            ).one()

    assert result["moved_departments"] == 1
    assert moved_root.parent_id == default_root.id
    assert moved_root.path == f"/{default_root.id}/{other_root.id}/"
    assert moved_child.path == f"/{default_root.id}/{other_root.id}/{child.id}/"
    execute_async.assert_awaited_once()

    await engine.dispose()
