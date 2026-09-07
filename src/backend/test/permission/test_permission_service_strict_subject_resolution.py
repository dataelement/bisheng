from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core import database as database_module
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.permission.domain.repositories.grant_subject_query_repository import (
    GrantSubjectQueryRepository,
)
from bisheng.permission.domain.services.permission_service import PermissionService


async def test_strict_relation_resolution_keeps_subject_repository_importable(monkeypatch):
    fga = AsyncMock()
    fga.read_tuples = AsyncMock(return_value=[])
    monkeypatch.setattr(PermissionService, "_aget_fga", AsyncMock(return_value=fga))

    token = set_current_tenant_id(17)
    try:
        resolved = await PermissionService.resolve_resource_relation_user_ids_strict(
            tenant_id=17,
            object_type="knowledge_space",
            object_id="151",
            relations=("owner", "manager"),
        )
    finally:
        current_tenant_id.reset(token)

    assert resolved == set()
    assert [call.kwargs["relation"] for call in fga.read_tuples.await_args_list] == ["owner", "manager"]


async def test_subject_repository_expands_only_active_users_in_the_requested_tenant(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        for statement in (
            "CREATE TABLE tenant (id INTEGER PRIMARY KEY, root_dept_id INTEGER, status VARCHAR(16))",
            "CREATE TABLE department (id INTEGER PRIMARY KEY, tenant_id INTEGER, path VARCHAR(512), "
            "status VARCHAR(16), is_tenant_root INTEGER, mounted_tenant_id INTEGER)",
            "CREATE TABLE user_department (department_id INTEGER, user_id INTEGER)",
            'CREATE TABLE "group" (id INTEGER PRIMARY KEY, tenant_id INTEGER)',
            "CREATE TABLE user_group (group_id INTEGER, user_id INTEGER, tenant_id INTEGER, is_group_admin INTEGER)",
            'CREATE TABLE "user" (user_id INTEGER PRIMARY KEY, "delete" INTEGER)',
            "CREATE TABLE user_tenant (user_id INTEGER, tenant_id INTEGER, status VARCHAR(16), is_active INTEGER)",
            "INSERT INTO tenant VALUES (1, 10, 'active'), (2, 20, 'active')",
            "INSERT INTO department VALUES "
            "(10, 1, '/10/', 'active', 0, NULL), "
            "(11, 1, '/10/11/', 'active', 0, NULL), "
            "(12, 1, '/10/12/', 'active', 0, NULL), "
            "(20, 2, '/10/20/', 'active', 1, 2), "
            "(21, 2, '/10/20/21/', 'active', 0, NULL)",
            "INSERT INTO user_department VALUES (11, 101), (21, 202)",
            'INSERT INTO "group" VALUES (31, 1), (32, 2)',
            "INSERT INTO user_group VALUES (31, 101, 1, 0), (31, 102, 1, 1), (32, 202, 2, 0)",
            'INSERT INTO "user" VALUES (101, 0), (102, 0), (103, 1), (202, 0)',
            "INSERT INTO user_tenant VALUES "
            "(101, 1, 'active', 1), (102, 1, 'active', 1), "
            "(103, 1, 'active', 1), (202, 2, 'active', 1)",
        ):
            await connection.exec_driver_sql(statement)

    @asynccontextmanager
    async def session_factory():
        async with AsyncSession(engine) as session:
            yield session

    monkeypatch.setattr(database_module, "get_async_db_session", session_factory)
    repository = GrantSubjectQueryRepository()
    try:
        assert await repository.resolve_exact_department_member_user_ids_batch(
            department_ids={11, 12, 21},
            tenant_id=1,
        ) == {11: {101}, 12: set()}
        assert await repository.resolve_user_group_member_user_ids_batch(
            group_ids={31, 32},
            tenant_id=1,
        ) == {31: {101, 102}}
        assert await repository.resolve_user_group_admin_user_ids_batch(
            group_ids={31, 32},
            tenant_id=1,
        ) == {31: {102}}
        assert await repository.filter_active_user_ids_in_tenant(
            user_ids={101, 102, 103, 202},
            tenant_id=1,
        ) == {101, 102}
    finally:
        await engine.dispose()
