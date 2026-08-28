"""Regression coverage for grant-subject user candidate scoping."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.database.models.department import DepartmentDao, UserDepartmentDao
from bisheng.permission.api.endpoints import resource_permission


@pytest.fixture()
async def engine():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.execute(
            text(
                'CREATE TABLE "user" ('
                "user_id INTEGER PRIMARY KEY, user_name VARCHAR(256) NOT NULL, "
                # Grant-subject queries withhold users flagged is_hidden=1.
                "is_hidden INTEGER NOT NULL DEFAULT 0, "
                'external_id VARCHAR(128), "delete" INTEGER NOT NULL DEFAULT 0)'
            )
        )
        await conn.execute(
            text(
                "CREATE TABLE user_tenant ("
                "id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, tenant_id INTEGER NOT NULL, "
                "status VARCHAR(16) NOT NULL)"
            )
        )
        await conn.execute(
            text(
                "CREATE TABLE department ("
                "id INTEGER PRIMARY KEY, path VARCHAR(512) NOT NULL, status VARCHAR(16) NOT NULL)"
            )
        )
        await conn.execute(
            text(
                "CREATE TABLE user_department ("
                "id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, department_id INTEGER NOT NULL)"
            )
        )
        await conn.execute(
            text(
                'INSERT INTO "user" (user_id, user_name, external_id, "delete") VALUES '
                "(1, 'Alice', 'a', 0), (2, 'Bob', 'b', 0), (3, 'CrossTenant', 'c', 0), "
                "(4, 'DisabledMember', 'd', 0), (5, 'Deleted', 'e', 1), (6, 'MultiDept', 'f', 0)"
            )
        )
        # Hidden user: is_hidden=1 must never appear among grant candidates,
        # unless the caller is a super admin (include_hidden).
        await conn.execute(
            text(
                "INSERT INTO \"user\" (user_id, user_name, external_id, \"delete\", is_hidden) "
                "VALUES (7, 'Hidden', 'g', 0, 1)"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO user_tenant (id, user_id, tenant_id, status) VALUES "
                "(1, 1, 1, 'active'), (2, 2, 1, 'active'), (3, 3, 2, 'active'), "
                "(4, 4, 1, 'disabled'), (5, 5, 1, 'active'), (6, 6, 1, 'active'), "
                "(7, 7, 1, 'active')"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO department (id, path, status) VALUES "
                "(10, '/10/', 'active'), (11, '/10/11/', 'active'), "
                "(12, '/10/12/', 'archived'), (20, '/20/', 'active')"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO user_department (id, user_id, department_id) VALUES "
                "(1, 1, 11), (2, 2, 20), (3, 3, 11), (4, 4, 11), "
                "(5, 5, 11), (6, 6, 10), (7, 6, 11), (8, 6, 12)"
            )
        )
    yield engine
    await engine.dispose()


@asynccontextmanager
async def _session_factory(engine):
    async with AsyncSession(engine) as session:
        yield session


async def test_department_scoped_candidates_use_path_exists_without_duplicates(engine):
    with (
        patch("bisheng.core.database.get_async_db_session", lambda: _session_factory(engine)),
        patch.object(UserDepartmentDao, "aget_by_user_ids", AsyncMock(return_value=[])),
        patch.object(DepartmentDao, "aget_by_ids", AsyncMock(return_value=[])),
    ):
        result = await resource_permission._list_knowledge_space_grant_users(
            tenant_id=1,
            keyword="",
            page=1,
            page_size=50,
            restrict_dept_path="/10/",
        )

    assert [item["user_id"] for item in result] == [6, 1]
    assert [item["external_id"] for item in result] == ["f", "a"]


async def test_normal_resource_candidates_only_require_active_tenant_membership(engine):
    with (
        patch("bisheng.core.database.get_async_db_session", lambda: _session_factory(engine)),
        patch.object(UserDepartmentDao, "aget_by_user_ids", AsyncMock(return_value=[])),
        patch.object(DepartmentDao, "aget_by_ids", AsyncMock(return_value=[])),
    ):
        result = await resource_permission._list_knowledge_space_grant_users(
            tenant_id=1,
            keyword="",
            page=1,
            page_size=50,
        )

    assert [item["user_id"] for item in result] == [6, 2, 1]


async def test_hidden_users_are_withheld_from_ordinary_callers(engine):
    with (
        patch("bisheng.core.database.get_async_db_session", lambda: _session_factory(engine)),
        patch.object(UserDepartmentDao, "aget_by_user_ids", AsyncMock(return_value=[])),
        patch.object(DepartmentDao, "aget_by_ids", AsyncMock(return_value=[])),
    ):
        result = await resource_permission._list_knowledge_space_grant_users(
            tenant_id=1,
            keyword="",
            page=1,
            page_size=50,
        )

    assert 7 not in [item["user_id"] for item in result]


async def test_hidden_users_are_visible_to_super_admins(engine):
    with (
        patch("bisheng.core.database.get_async_db_session", lambda: _session_factory(engine)),
        patch.object(UserDepartmentDao, "aget_by_user_ids", AsyncMock(return_value=[])),
        patch.object(DepartmentDao, "aget_by_ids", AsyncMock(return_value=[])),
    ):
        result = await resource_permission._list_knowledge_space_grant_users(
            tenant_id=1,
            keyword="",
            page=1,
            page_size=50,
            include_hidden=True,
        )

    assert [item["user_id"] for item in result] == [7, 6, 2, 1]
