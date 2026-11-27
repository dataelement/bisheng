"""Exercise role-list filtering and read-only flags together against SQLite."""

from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.database.models.department import DepartmentDao, UserDepartment
from bisheng.database.models.role import Role, RoleDao
from bisheng.database.models.user_role import UserRole
from bisheng.role.domain.services.role_service import RoleService
from bisheng.user.domain.models.user import User


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


async def test_list_roles_search_by_assigned_username_and_scope(monkeypatch):
    """验证按角色名或关联用户名搜索时的去重、分页稳定性及租户/部门隔离。"""
    monkeypatch.setattr(RoleDao, "aget_user_count_by_role_ids", AsyncMock(return_value={}))
    for name in (
        "_get_department_names",
        "_department_scope_paths_for_roles",
        "_get_role_creator_ids",
        "_get_creator_names",
    ):
        monkeypatch.setattr(RoleService, name, AsyncMock(return_value={}))

    same_time = datetime(2026, 11, 26, 12, 0, 0)
    engine = create_async_engine("sqlite+aiosqlite://")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Role.__table__.create)
            await connection.run_sync(User.__table__.create)
            await connection.execute(
                sa_text(
                    "CREATE TABLE userrole ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "user_id INTEGER NOT NULL, "
                    "role_id INTEGER NOT NULL, "
                    "tenant_id INTEGER NOT NULL DEFAULT 1, "
                    "create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, "
                    "update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL)"
                )
            )
            await connection.run_sync(UserDepartment.__table__.create)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            session.add_all(
                [
                    Role(id=1, role_name="System", role_type="global", tenant_id=1, create_time=same_time),
                    Role(id=2, role_name="Shared", role_type="global", tenant_id=1, create_time=same_time),
                    Role(id=10, role_name="alice_team", role_type="tenant", tenant_id=10, department_id=31, create_time=same_time),
                    Role(id=11, role_name="LocalDept31", role_type="tenant", tenant_id=10, department_id=31, create_time=same_time),
                    Role(id=12, role_name="LocalAllDept", role_type="tenant", tenant_id=10, department_id=None, create_time=same_time),
                    Role(id=20, role_name="ForeignTenantRole", role_type="tenant", tenant_id=11, department_id=41, create_time=same_time),
                ]
            )
            session.add_all(
                [
                    User(user_id=101, user_name="alice_dept31", password="x"),
                    User(user_id=102, user_name="alice_dept32", password="x"),
                    User(user_id=103, user_name="alice_tenant11", password="x"),
                    User(user_id=104, user_name="bob_special%_name", password="x"),
                ]
            )
            session.add_all(
                [
                    # 租户10 部门31 用户同时关联 2、10（与角色名双重命中）、11
                    UserRole(id=1, user_id=101, role_id=2, tenant_id=10),
                    UserRole(id=2, user_id=101, role_id=10, tenant_id=10),
                    UserRole(id=3, user_id=101, role_id=11, tenant_id=10),
                    # 租户10 部门32 用户关联全局作用域租户角色 12
                    UserRole(id=4, user_id=102, role_id=12, tenant_id=10),
                    # 租户11 用户关联共享角色 2 与租户11 角色 20
                    UserRole(id=5, user_id=103, role_id=2, tenant_id=11),
                    UserRole(id=6, user_id=103, role_id=20, tenant_id=11),
                    # 特殊字符用户名关联角色 11
                    UserRole(id=7, user_id=104, role_id=11, tenant_id=10),
                ]
            )
            session.add_all(
                [
                    UserDepartment(id=1, user_id=101, department_id=31),
                    UserDepartment(id=2, user_id=102, department_id=32),
                    UserDepartment(id=3, user_id=103, department_id=41),
                    UserDepartment(id=4, user_id=104, department_id=31),
                ]
            )
            await session.commit()

            @asynccontextmanager
            async def database_session():
                yield session

            monkeypatch.setattr("bisheng.database.models.role.get_async_db_session", database_session)

            # 1) 租户10 管理员：搜 alice 命中角色 2/10/11/12（去重且不命中租户11），且同时间按 ID 倒序稳定跨页
            tenant_admin = SimpleNamespace(user_id=82, tenant_id=10, is_global_super=False, is_admin=lambda: False)
            monkeypatch.setattr(DepartmentDao, "aget_user_admin_departments", AsyncMock(return_value=[]))
            monkeypatch.setattr("bisheng.permission.application.is_tenant_admin", AsyncMock(return_value=True))

            page1 = await RoleService.list_roles(keyword="alice", page=1, limit=2, login_user=tenant_admin)
            page2 = await RoleService.list_roles(keyword="alice", page=2, limit=2, login_user=tenant_admin)
            assert page1["total"] == 4
            assert page2["total"] == 4
            assert [r.id for r in page1["data"]] == [12, 11]
            assert [r.id for r in page2["data"]] == [10, 2]

            # 租户10 管理员搜租户11 专属用户名：共享角色 2 不应被租户11 的用户绑定命中
            cross_tenant = await RoleService.list_roles(keyword="alice_tenant11", page=1, limit=10, login_user=tenant_admin)
            assert cross_tenant["total"] == 0
            assert cross_tenant["data"] == []

            # 特殊字符 % 应被正确转义，仅命中 bob_special%_name 对应的角色 11
            special = await RoleService.list_roles(keyword="special%", page=1, limit=10, login_user=tenant_admin)
            assert special["total"] == 1
            assert [r.id for r in special["data"]] == [11]

            # 清空搜索恢复可见全集
            cleared = await RoleService.list_roles(keyword="   ", page=1, limit=10, login_user=tenant_admin)
            assert cleared["total"] == 4
            assert {r.id for r in cleared["data"]} == {2, 10, 11, 12}

            # 2) 租户10 部门31 管理员：角色 12 虽可见但绑定用户 102 在部门32，搜 alice_dept32 不应命中
            monkeypatch.setattr(
                DepartmentDao,
                "aget_user_admin_departments",
                AsyncMock(return_value=[SimpleNamespace(id=31, path="/1/31/")]),
            )
            monkeypatch.setattr(DepartmentDao, "aget_subtree_ids", AsyncMock(return_value=[31]))
            dept_hit = await RoleService.list_roles(keyword="alice_dept31", page=1, limit=10, login_user=tenant_admin)
            assert dept_hit["total"] == 3
            assert {r.id for r in dept_hit["data"]} == {2, 10, 11}
            dept_isolated = await RoleService.list_roles(keyword="alice_dept32", page=1, limit=10, login_user=tenant_admin)
            assert dept_isolated["total"] == 0
            assert dept_isolated["data"] == []

            # 3) 平台超管：切到租户10视图不命中租户11用户；切到租户11视图可命中角色 2 与 20
            super_admin = SimpleNamespace(user_id=1, tenant_id=1, is_global_super=True, is_admin=lambda: True)
            monkeypatch.setattr("bisheng.core.context.tenant.is_management_all_tenants", lambda: False)
            monkeypatch.setattr("bisheng.core.context.tenant.get_admin_scope_tenant_id", lambda: 10)
            scoped = await RoleService.list_roles(keyword="alice_tenant11", page=1, limit=10, login_user=super_admin)
            assert scoped["total"] == 0

            monkeypatch.setattr("bisheng.core.context.tenant.get_admin_scope_tenant_id", lambda: 11)
            tenant11_view = await RoleService.list_roles(keyword="alice_tenant11", page=1, limit=10, login_user=super_admin)
            assert tenant11_view["total"] == 2
            assert {r.id for r in tenant11_view["data"]} == {2, 20}
    finally:
        await engine.dispose()
