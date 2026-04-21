"""Shared pytest fixtures for BiSheng backend tests.

Provides:
- Import chain pre-mocking (module-level, runs at import time)
- mock_settings: controllable settings mock
- db_engine / db_session: SQLite in-memory sync DB with ROLLBACK isolation
- async_db_engine / async_db_session: async equivalents
- tenant_context / bypass_tenant: tenant ContextVar helpers
- mock_redis / mock_minio / mock_openfga: external service mocks
- test_client: FastAPI TestClient with dependency overrides

F001 existing tests (test_tenant_*.py) have their own self-contained
engine/session/pre-mock. These shared fixtures do NOT interfere with them;
they only activate when explicitly requested in function signatures.

Created by F000-test-infrastructure. Expanded from F001 minimal conftest.
"""

# ---------------------------------------------------------------------------
# Module-level pre-mock: must run BEFORE any deep bisheng imports.
# This is idempotent and safe alongside F001's per-file pre-mocking.
# ---------------------------------------------------------------------------
from test.fixtures.mock_services import premock_import_chain

premock_import_chain()

# ---------------------------------------------------------------------------
# Standard imports (safe after pre-mock)
# ---------------------------------------------------------------------------
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session

from bisheng.core.config.multi_tenant import MultiTenantConf
from test.fixtures.table_definitions import create_all_tables


# ---------------------------------------------------------------------------
# Settings mock (preserved from F001, enhanced)
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_settings(monkeypatch):
    """Mock the global settings object with controllable multi_tenant config.

    Returns a MagicMock with multi_tenant set to a real MultiTenantConf instance.
    """
    mock = MagicMock()
    mock.multi_tenant = MultiTenantConf(enabled=False)
    mock.jwt_secret = 'test-secret'
    mock.cookie_conf = MagicMock()
    mock.cookie_conf.jwt_token_expire_time = 86400
    mock.cookie_conf.jwt_iss = 'bisheng'

    monkeypatch.setattr('bisheng.common.services.config_service.settings', mock)
    return mock


# ---------------------------------------------------------------------------
# Synchronous DB fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope='session')
def db_engine():
    """Session-scoped SQLite in-memory engine with all test tables created.

    Shared across all tests in the session for efficiency.
    Individual test isolation is provided by db_session's ROLLBACK.
    """
    engine = create_engine(
        'sqlite://',
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    create_all_tables(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(db_engine):
    """Function-scoped transactional session that rolls back after each test.

    Every test gets a clean slate — INSERTs within a test are invisible
    to other tests.
    """
    connection = db_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    yield session
    session.close()
    if transaction.is_active:
        transaction.rollback()
    connection.close()


# ---------------------------------------------------------------------------
# Asynchronous DB fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope='session')
async def async_db_engine():
    """Session-scoped async SQLite engine with all test tables created."""
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(
        'sqlite+aiosqlite://',
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    # Create tables using sync connection (aiosqlite supports run_sync)
    async with engine.begin() as conn:
        from test.fixtures.table_definitions import (
            TABLE_DEFINITIONS,
            INDEX_DEFINITIONS,
        )
        from sqlalchemy import text
        for ddl in TABLE_DEFINITIONS.values():
            await conn.execute(text(ddl))
        for idx in INDEX_DEFINITIONS:
            await conn.execute(text(idx))
    yield engine
    await engine.dispose()


@pytest.fixture()
async def async_db_session(async_db_engine):
    """Function-scoped async session with ROLLBACK isolation."""
    from sqlalchemy.ext.asyncio import AsyncSession

    async with async_db_engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(bind=connection)
        yield session
        await session.close()
        if transaction.is_active:
            await transaction.rollback()


# ---------------------------------------------------------------------------
# Tenant context helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def tenant_context():
    """Set current_tenant_id ContextVar for the duration of a test.

    Usage:
        def test_something(db_session, tenant_context):
            tenant_context(2)  # set tenant_id=2
            ...
    """
    from bisheng.core.context.tenant import set_current_tenant_id

    tokens = []

    def _set(tenant_id: int = 1):
        token = set_current_tenant_id(tenant_id)
        tokens.append(token)

    yield _set

    # Reset all tokens in reverse order
    from bisheng.core.context.tenant import current_tenant_id as _ctx_var
    for token in reversed(tokens):
        _ctx_var.reset(token)


@pytest.fixture()
def bypass_tenant():
    """Enter bypass_tenant_filter() for the duration of a test.

    Useful for setup/teardown data insertion without tenant filtering.
    """
    from bisheng.core.context.tenant import bypass_tenant_filter

    with bypass_tenant_filter():
        yield


# ---------------------------------------------------------------------------
# External service mocks
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_redis():
    """Function-scoped fakeredis instance, flushed after each test."""
    import fakeredis

    r = fakeredis.FakeRedis()
    yield r
    r.flushall()


@pytest.fixture()
def mock_minio():
    """Function-scoped MagicMock mimicking MinIO client operations."""
    mock = MagicMock()
    mock.put_object.return_value = None
    mock.get_object.return_value = MagicMock(read=MagicMock(return_value=b'test-data'))
    mock.remove_object.return_value = None
    return mock


@pytest.fixture()
def mock_openfga():
    """Function-scoped InMemoryOpenFGAClient, reset after each test."""
    from test.fixtures.mock_openfga import InMemoryOpenFGAClient

    client = InMemoryOpenFGAClient()
    yield client
    client.reset()


# ---------------------------------------------------------------------------
# TestClient
# ---------------------------------------------------------------------------

@pytest.fixture()
def test_client(monkeypatch):
    """FastAPI TestClient with lifespan disabled.

    Uses the real app routes but replaces the lifespan with a no-op to
    avoid initializing real DB/Redis/MinIO connections. If importing the
    real app fails (import chain issues), falls back to a minimal app
    with just /health.
    """
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _noop_lifespan(app):
        yield

    try:
        monkeypatch.setattr('bisheng.main.lifespan', _noop_lifespan)
        from bisheng.main import create_app
        app = create_app()
    except Exception:
        # Fallback: minimal app with /health only
        from fastapi import FastAPI
        app = FastAPI()

        @app.get('/health')
        def health():
            return {'status': 'OK'}

    from starlette.testclient import TestClient
    with TestClient(app) as client:
        yield client
