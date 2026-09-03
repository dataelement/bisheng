"""T002 — ``DepartmentTreeNode.short_name`` exposure on ``GET /departments/tree``.

Part of F058-dashboard-enhancement (AC-04). Mirrors the FastAPI TestClient +
in-memory SQLite harness used by ``test/test_department_api.py``.
"""

import sys
from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.testclient import TestClient

for mod in ("celery", "celery.schedules", "celery.app", "celery.app.task"):
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()
from test.fixtures.mock_services import premock_import_chain

premock_import_chain()

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.department.api.router import router as department_router

_DEPARTMENT_DDL = """
    CREATE TABLE IF NOT EXISTS department (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dept_id VARCHAR(64) NOT NULL UNIQUE,
        name VARCHAR(128) NOT NULL,
        short_name VARCHAR(64),
        parent_id INTEGER,
        tenant_id INTEGER NOT NULL DEFAULT 1,
        path VARCHAR(512) NOT NULL DEFAULT '',
        sort_order INTEGER DEFAULT 0,
        source VARCHAR(32) DEFAULT 'local',
        external_id VARCHAR(128),
        status VARCHAR(16) DEFAULT 'active',
        is_tenant_root INTEGER NOT NULL DEFAULT 0,
        mounted_tenant_id INTEGER,
        is_deleted INTEGER NOT NULL DEFAULT 0,
        last_sync_ts BIGINT NOT NULL DEFAULT 0,
        sync_parent_external_id VARCHAR(128),
        default_role_ids JSON,
        concurrent_session_limit INTEGER NOT NULL DEFAULT 0,
        org_level VARCHAR(32),
        create_user INTEGER,
        create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        UNIQUE(source, external_id)
    )
"""

_TENANT_DDL = """
    CREATE TABLE IF NOT EXISTS tenant (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_code VARCHAR(64) NOT NULL UNIQUE,
        tenant_name VARCHAR(128) NOT NULL,
        logo VARCHAR(512),
        root_dept_id INTEGER,
        status VARCHAR(16) NOT NULL DEFAULT 'active',
        parent_tenant_id INTEGER,
        share_default_to_children INTEGER NOT NULL DEFAULT 0,
        contact_name VARCHAR(64),
        contact_phone VARCHAR(32),
        contact_email VARCHAR(128),
        quota_config JSON,
        storage_config JSON,
        create_user INTEGER,
        create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
    )
"""


class MockAdminUser:
    user_id = 1
    user_name = "admin"
    user_role = [1]
    tenant_id = 1
    group_cache = {}


@pytest.fixture()
def async_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    import asyncio

    loop = asyncio.new_event_loop()
    loop.run_until_complete(_setup(engine))
    loop.close()
    yield engine


async def _setup(engine):
    async with engine.begin() as conn:
        await conn.execute(text(_DEPARTMENT_DDL))
        await conn.execute(text(_TENANT_DDL))
        await conn.execute(
            text(
                "INSERT INTO department (dept_id, name, short_name, org_level, parent_id, path, sort_order) "
                "VALUES ('d1', '生产制造部', '生产部', 'company', NULL, '/1/', 1)"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO department (dept_id, name, short_name, parent_id, path, sort_order) "
                "VALUES ('d2', '安全环保监察部', NULL, NULL, '/2/', 2)"
            )
        )


@pytest.fixture()
def client(async_engine):
    @asynccontextmanager
    async def mock_get_async_db_session():
        async with async_engine.connect() as conn:
            trans = await conn.begin()
            session = AsyncSession(bind=conn)
            try:
                yield session
            finally:
                await session.close()
                if trans.is_active:
                    await trans.rollback()

    app = FastAPI()
    app.include_router(department_router, prefix="/api/v1")

    async def get_admin_user():
        return MockAdminUser()

    app.dependency_overrides[UserPayload.get_login_user] = get_admin_user

    with (
        patch(
            "bisheng.department.domain.services.department_service.get_async_db_session",
            mock_get_async_db_session,
        ),
        patch(
            "bisheng.database.models.tenant.get_async_db_session",
            mock_get_async_db_session,
        ),
    ):
        with TestClient(app) as c:
            yield c


def test_tree_exposes_short_name_when_present(client):
    """AC-04: a department with a maintained short_name surfaces it on the tree node."""
    resp = client.get("/api/v1/departments/tree")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status_code"] == 200
    by_name = {node["name"]: node for node in body["data"]}
    assert by_name["生产制造部"]["short_name"] == "生产部"
    assert by_name["生产制造部"]["org_level"] == "company"


def test_tree_short_name_none_when_not_maintained(client):
    """AC-04: a department without a maintained short_name reports short_name=None, not an error."""
    resp = client.get("/api/v1/departments/tree")
    assert resp.status_code == 200
    body = resp.json()
    by_name = {node["name"]: node for node in body["data"]}
    assert by_name["安全环保监察部"]["short_name"] is None
