"""Integration tests for SQLAlchemy tenant filter events.

Uses SQLite in-memory with test-only models.
Verifies AC-04, AC-05, AC-06, AC-11.
"""

import sys
from unittest.mock import MagicMock

import pytest
from sqlalchemy import Column, Integer, String, create_engine, event, text
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, SQLModel, Session, select

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.config.multi_tenant import MultiTenantConf
from bisheng.core.context.tenant import (
    DEFAULT_TENANT_ID,
    bypass_tenant_filter,
    current_tenant_id,
    set_current_tenant_id,
)

# Pre-mock modules that trigger import chain issues
_MOCK_MODULES = [
    'bisheng.common.services',
    'bisheng.common.services.config_service',
    'bisheng.common.services.telemetry',
    'bisheng.common.services.telemetry.telemetry_service',
]
for _m in _MOCK_MODULES:
    if _m not in sys.modules:
        _mock = MagicMock()
        if _m == 'bisheng.common.services.config_service':
            _mock.settings = MagicMock()
            _mock.settings.multi_tenant = MultiTenantConf(enabled=False)
        sys.modules[_m] = _mock


# ---------------------------------------------------------------------------
# Test-only models
# ---------------------------------------------------------------------------

class _TenantTestItem(SQLModelSerializable, table=True):
    __tablename__ = '_tenant_test_item'
    id: int = Field(default=None, sa_column=Column(Integer, primary_key=True, autoincrement=True))
    name: str = Field(sa_column=Column(String(64), nullable=False))
    tenant_id: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text('0')))


class _NoTenantItem(SQLModelSerializable, table=True):
    __tablename__ = '_no_tenant_item'
    id: int = Field(default=None, sa_column=Column(Integer, primary_key=True, autoincrement=True))
    value: str = Field(sa_column=Column(String(64), nullable=False))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Store event handler references for cleanup
_registered_handlers = {}


@pytest.fixture()
def filter_engine():
    """Create a fresh SQLite engine with tenant filter events registered."""
    from bisheng.core.database import tenant_filter

    # Reset module state
    tenant_filter._initialized = False
    tenant_filter._tenant_aware_tables = set()

    engine = create_engine(
        'sqlite://',
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    _TenantTestItem.__table__.create(engine, checkfirst=True)
    _NoTenantItem.__table__.create(engine, checkfirst=True)

    # Register events
    tenant_filter.register_tenant_filter_events()

    yield engine

    # Reset state (don't try to remove listeners — they'll be cleaned up on next register)
    tenant_filter._initialized = False
    tenant_filter._tenant_aware_tables = set()
    engine.dispose()


@pytest.fixture()
def session(filter_engine):
    connection = filter_engine.connect()
    transaction = connection.begin()
    sess = Session(bind=connection)
    yield sess
    sess.close()
    if transaction.is_active:
        transaction.rollback()
    connection.close()


def _set_mock_settings(enabled: bool):
    """Update the mock settings for multi_tenant.enabled."""
    mock = sys.modules['bisheng.common.services.config_service']
    mock.settings.multi_tenant = MultiTenantConf(enabled=enabled)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSelectAutoFilter:
    """AC-04: SELECT queries auto-filter by tenant_id."""

    def test_select_auto_filter(self, session):
        with bypass_tenant_filter():
            session.add(_TenantTestItem(name='t1_item', tenant_id=1))
            session.add(_TenantTestItem(name='t2_item', tenant_id=2))
            session.commit()

        _set_mock_settings(enabled=False)
        token = set_current_tenant_id(1)
        try:
            results = session.exec(select(_TenantTestItem)).all()
        finally:
            current_tenant_id.reset(token)

        assert len(results) == 1
        assert results[0].name == 't1_item'


class TestInsertAutoFill:
    """AC-05: INSERT auto-fills tenant_id from context."""

    def test_insert_auto_fill(self, session):
        _set_mock_settings(enabled=False)
        token = set_current_tenant_id(5)
        try:
            item = _TenantTestItem(name='auto_fill')
            session.add(item)
            session.flush()
        finally:
            current_tenant_id.reset(token)

        assert item.tenant_id == 5


class TestBypass:
    """AC-06: bypass_tenant_filter skips filtering."""

    def test_bypass_returns_all(self, session):
        with bypass_tenant_filter():
            session.add(_TenantTestItem(name='a', tenant_id=1))
            session.add(_TenantTestItem(name='b', tenant_id=2))
            session.add(_TenantTestItem(name='c', tenant_id=3))
            session.commit()

        with bypass_tenant_filter():
            results = session.exec(select(_TenantTestItem)).all()

        assert len(results) == 3


class TestEnabledDisabled:
    """AC-11: Behavior differs based on multi_tenant.enabled."""

    def test_no_context_disabled_uses_default(self, session):
        with bypass_tenant_filter():
            session.add(_TenantTestItem(name='default', tenant_id=DEFAULT_TENANT_ID))
            session.add(_TenantTestItem(name='other', tenant_id=99))
            session.commit()

        _set_mock_settings(enabled=False)
        token = current_tenant_id.set(None)
        try:
            results = session.exec(select(_TenantTestItem)).all()
        finally:
            current_tenant_id.reset(token)

        assert len(results) == 1
        assert results[0].name == 'default'

    def test_no_context_enabled_raises(self, session):
        from bisheng.common.errcode.tenant import NoTenantContextError

        _set_mock_settings(enabled=True)
        token = current_tenant_id.set(None)
        try:
            with pytest.raises(NoTenantContextError):
                session.exec(select(_TenantTestItem)).all()
        finally:
            current_tenant_id.reset(token)
            _set_mock_settings(enabled=False)


class TestNonTenantTable:

    def test_non_tenant_table_unaffected(self, session):
        with bypass_tenant_filter():
            session.add(_NoTenantItem(value='hello'))
            session.add(_NoTenantItem(value='world'))
            session.commit()

        token = set_current_tenant_id(99)
        try:
            results = session.exec(select(_NoTenantItem)).all()
        finally:
            current_tenant_id.reset(token)

        assert len(results) == 2
