"""Exercise role-list filtering and read-only flags together against SQLite."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.database.models.department import DepartmentDao
from bisheng.database.models.role import Role, RoleDao
from bisheng.role.domain.services.role_service import RoleService


@pytest.mark.parametrize("department_admin", [False, True])
@pytest.mark.parametrize("limit", [1, 10])
async def test_admin_lists_include_readonly_global_roles(monkeypatch, department_admin, limit):
    actor = SimpleNamespace(user_id=82, tenant_id=10, is_global_super=False, is_admin=lambda: False)
    departments = [SimpleNamespace(id=31, path="/1/31/")] if department_admin else []
    monkeypatch.setattr(DepartmentDao, "aget_user_admin_departments", AsyncMock(return_value=departments))
    monkeypatch.setattr(DepartmentDao, "aget_subtree_ids", AsyncMock(return_value=[31]))
    monkeypatch.setattr("bisheng.permission.application.is_tenant_admin", AsyncMock(return_value=True))
    monkeypatch.setattr(RoleDao, "aget_user_count_by_role_ids", AsyncMock(return_value={}))
    for name in (
        "_get_department_names",
        "_department_scope_paths_for_roles",
        "_get_role_creator_ids",
        "_get_creator_names",
    ):
        monkeypatch.setattr(RoleService, name, AsyncMock(return_value={}))

    engine = create_async_engine("sqlite+aiosqlite://")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Role.__table__.create)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            session.add_all(
                [
                    Role(id=1, role_name="System", role_type="global", tenant_id=1),
                    Role(id=2, role_name="Shared", role_type="global", tenant_id=1),
                    Role(id=3, role_name="Shared scoped", role_type="global", tenant_id=1, department_id=99),
                    Role(id=211, role_name="Local", role_type="tenant", tenant_id=10, department_id=31),
                    Role(id=212, role_name="Other department", role_type="tenant", tenant_id=10, department_id=32),
                    Role(id=213, role_name="Foreign", role_type="tenant", tenant_id=11, department_id=31),
                ]
            )
            await session.commit()

            @asynccontextmanager
            async def database_session():
                yield session

            monkeypatch.setattr("bisheng.database.models.role.get_async_db_session", database_session)
            result = await RoleService.list_roles(keyword=None, page=1, limit=limit, login_user=actor)
            expected = {2, 3, 211} if department_admin else {2, 3, 211, 212}
            assert result["total"] == len(expected)
            assert len(result["data"]) == min(limit, len(expected))
            assert {row.id for row in result["data"]} <= expected
            if limit == 10:
                assert {row.id for row in result["data"]} == expected
                shared = [row for row in result["data"] if row.role_type == "global"]
                assert {row.id for row in shared} == {2, 3}
                assert all(row.is_readonly for row in shared)
    finally:
        await engine.dispose()
