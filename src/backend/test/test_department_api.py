"""API integration tests for Department endpoints.

Uses a minimal FastAPI app with department router + in-memory SQLite.
The UserPayload dependency is overridden to provide a mock login_user.

Part of F002-department-tree.
"""

import pytest
from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from sqlalchemy import create_engine, text
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient


# ---------------------------------------------------------------------------
# Setup: Create minimal app with department routes
# ---------------------------------------------------------------------------

# Pre-mock heavy imports before any bisheng import
import sys
for mod in ('celery', 'celery.schedules', 'celery.app', 'celery.app.task'):
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()
from test.fixtures.mock_services import premock_import_chain
premock_import_chain()

from bisheng.department.api.router import router as department_router
from bisheng.common.dependencies.user_deps import UserPayload


class MockAdminUser:
    """Mock admin login user."""
    user_id = 1
    user_name = 'admin'
    user_role = [1]  # AdminRole
    tenant_id = 1
    group_cache = {}


class MockNonAdminUser:
    """Mock non-admin login user."""
    user_id = 99
    user_name = 'viewer'
    user_role = [2]
    tenant_id = 1
    group_cache = {}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope='module')
def api_engine():
    """Sync SQLite engine for setup/data insertion."""
    engine = create_engine(
        'sqlite://',
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS department (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dept_id VARCHAR(64) NOT NULL UNIQUE,
                name VARCHAR(128) NOT NULL,
                parent_id INTEGER,
                tenant_id INTEGER NOT NULL DEFAULT 1,
                path VARCHAR(512) NOT NULL DEFAULT '',
                sort_order INTEGER DEFAULT 0,
                source VARCHAR(32) DEFAULT 'local',
                external_id VARCHAR(128),
                status VARCHAR(16) DEFAULT 'active',
                is_tenant_root INTEGER NOT NULL DEFAULT 0,
                mounted_tenant_id INTEGER,
                default_role_ids JSON,
                create_user INTEGER,
                create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                UNIQUE(source, external_id)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS user_department (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                department_id INTEGER NOT NULL,
                is_primary INTEGER DEFAULT 1,
                source VARCHAR(32) DEFAULT 'local',
                create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                UNIQUE(user_id, department_id)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS user (
                user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_name VARCHAR(255) UNIQUE,
                password VARCHAR(255) NOT NULL DEFAULT 'hashed',
                "delete" INTEGER DEFAULT 0,
                create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                password_update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tenant (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_code VARCHAR(64) NOT NULL UNIQUE,
                tenant_name VARCHAR(128) NOT NULL,
                logo VARCHAR(512),
                root_dept_id INTEGER,
                status VARCHAR(16) NOT NULL DEFAULT 'active',
                contact_name VARCHAR(64),
                contact_phone VARCHAR(32),
                contact_email VARCHAR(128),
                quota_config JSON,
                storage_config JSON,
                create_user INTEGER,
                create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
            )
        """))
    yield engine
    engine.dispose()


@pytest.fixture(scope='module')
def async_engine(api_engine):
    """Async engine sharing the same SQLite database via StaticPool."""
    # We cannot truly share an in-memory SQLite between sync and async engines.
    # Instead, we create a separate async engine and set up tables there.
    engine = create_async_engine(
        'sqlite+aiosqlite://',
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    import asyncio
    loop = asyncio.new_event_loop()
    loop.run_until_complete(_setup_async_tables(engine))
    loop.close()
    yield engine


async def _setup_async_tables(engine):
    """Create tables in async engine."""
    async with engine.begin() as conn:
        for ddl in [
            """CREATE TABLE IF NOT EXISTS department (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dept_id VARCHAR(64) NOT NULL UNIQUE,
                name VARCHAR(128) NOT NULL,
                parent_id INTEGER,
                tenant_id INTEGER NOT NULL DEFAULT 1,
                path VARCHAR(512) NOT NULL DEFAULT '',
                sort_order INTEGER DEFAULT 0,
                source VARCHAR(32) DEFAULT 'local',
                external_id VARCHAR(128),
                status VARCHAR(16) DEFAULT 'active',
                is_tenant_root INTEGER NOT NULL DEFAULT 0,
                mounted_tenant_id INTEGER,
                default_role_ids JSON,
                create_user INTEGER,
                create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                UNIQUE(source, external_id)
            )""",
            """CREATE TABLE IF NOT EXISTS user_department (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                department_id INTEGER NOT NULL,
                is_primary INTEGER DEFAULT 1,
                source VARCHAR(32) DEFAULT 'local',
                create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                UNIQUE(user_id, department_id)
            )""",
            """CREATE TABLE IF NOT EXISTS user (
                user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_name VARCHAR(255) UNIQUE,
                password VARCHAR(255) NOT NULL DEFAULT 'hashed',
                "delete" INTEGER DEFAULT 0,
                create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                password_update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS tenant (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_code VARCHAR(64) NOT NULL UNIQUE,
                tenant_name VARCHAR(128) NOT NULL,
                logo VARCHAR(512),
                root_dept_id INTEGER,
                status VARCHAR(16) NOT NULL DEFAULT 'active',
                contact_name VARCHAR(64),
                contact_phone VARCHAR(32),
                contact_email VARCHAR(128),
                quota_config JSON,
                storage_config JSON,
                create_user INTEGER,
                create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
            )""",
        ]:
            await conn.execute(text(ddl))


@pytest.fixture()
def client(async_engine):
    """TestClient with mocked DB session and admin user."""

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
    app.include_router(department_router, prefix='/api/v1')

    # Override UserPayload dependency
    async def get_admin_user():
        return MockAdminUser()

    app.dependency_overrides[UserPayload.get_login_user] = get_admin_user

    with patch(
        'bisheng.department.domain.services.department_service.get_async_db_session',
        mock_get_async_db_session,
    ):
        with TestClient(app) as c:
            yield c


@pytest.fixture()
def non_admin_client(async_engine):
    """TestClient with non-admin user."""

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
    app.include_router(department_router, prefix='/api/v1')

    async def get_non_admin():
        return MockNonAdminUser()

    app.dependency_overrides[UserPayload.get_login_user] = get_non_admin

    with patch(
        'bisheng.department.domain.services.department_service.get_async_db_session',
        mock_get_async_db_session,
    ):
        with TestClient(app) as c:
            yield c


class TestDepartmentAPI:

    def test_create_department_parent_not_found(self, client):
        """AC-01 error path: parent_id doesn't exist returns 21000."""
        resp = client.post('/api/v1/departments', json={
            'name': 'Engineering',
            'parent_id': 1,
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body['status_code'] == 21000

    def test_get_tree_empty(self, client):
        """AC-03: GET /departments/tree with no departments returns empty list."""
        resp = client.get('/api/v1/departments/tree')
        assert resp.status_code == 200
        body = resp.json()
        assert body['status_code'] == 200
        assert body['data'] == []

    def test_get_department_not_found(self, client):
        """AC-04: GET /departments/{dept_id} with non-existent dept returns 21000."""
        resp = client.get('/api/v1/departments/BS@nonexist')
        assert resp.status_code == 200
        body = resp.json()
        assert body['status_code'] == 21000

    def test_update_department_not_found(self, client):
        """PUT with non-existent dept_id returns 21000."""
        resp = client.put('/api/v1/departments/BS@nonexist', json={
            'name': 'NewName',
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body['status_code'] == 21000

    def test_delete_department_not_found(self, client):
        """DELETE with non-existent dept_id returns 21000."""
        resp = client.delete('/api/v1/departments/BS@nonexist')
        assert resp.status_code == 200
        body = resp.json()
        assert body['status_code'] == 21000

    def test_move_department_not_found(self, client):
        """POST move with non-existent dept_id returns 21000."""
        resp = client.post('/api/v1/departments/BS@nonexist/move', json={
            'new_parent_id': 1,
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body['status_code'] == 21000

    def test_get_members_not_found(self, client):
        """GET members of non-existent dept returns 21000."""
        resp = client.get('/api/v1/departments/BS@nonexist/members')
        assert resp.status_code == 200
        body = resp.json()
        assert body['status_code'] == 21000

    def test_add_members_not_found(self, client):
        """POST members to non-existent dept returns 21000."""
        resp = client.post('/api/v1/departments/BS@nonexist/members', json={
            'user_ids': [1],
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body['status_code'] == 21000

    def test_remove_member_not_found(self, client):
        """DELETE member from non-existent dept returns 21000."""
        resp = client.delete('/api/v1/departments/BS@nonexist/members/1')
        assert resp.status_code == 200
        body = resp.json()
        assert body['status_code'] == 21000


class TestDepartmentPermission:

    def test_permission_denied(self, non_admin_client):
        """AC-16: Non-admin user gets 21009 on department operations."""
        resp = non_admin_client.get('/api/v1/departments/tree')
        assert resp.status_code == 200
        body = resp.json()
        assert body['status_code'] == 21009

    def test_permission_denied_create(self, non_admin_client):
        """Non-admin cannot create departments."""
        resp = non_admin_client.post('/api/v1/departments', json={
            'name': 'Test', 'parent_id': 1,
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body['status_code'] == 21009

    def test_permission_denied_delete(self, non_admin_client):
        """Non-admin cannot delete departments."""
        resp = non_admin_client.delete('/api/v1/departments/BS@test')
        assert resp.status_code == 200
        body = resp.json()
        assert body['status_code'] == 21009

    def test_permission_denied_members(self, non_admin_client):
        """Non-admin cannot manage members."""
        resp = non_admin_client.post('/api/v1/departments/BS@test/members', json={
            'user_ids': [1],
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body['status_code'] == 21009


class TestDepartmentValidation:

    def test_create_invalid_name_too_short(self, client):
        """Name must be 2-50 chars."""
        resp = client.post('/api/v1/departments', json={
            'name': 'A',  # too short
            'parent_id': 1,
        })
        assert resp.status_code == 422  # Pydantic validation error

    def test_create_missing_parent_id(self, client):
        """parent_id is required."""
        resp = client.post('/api/v1/departments', json={
            'name': 'Test Dept',
        })
        assert resp.status_code == 422

    def test_add_members_empty_user_ids(self, client):
        """user_ids must have at least 1 element."""
        resp = client.post('/api/v1/departments/BS@test/members', json={
            'user_ids': [],
        })
        assert resp.status_code == 422
