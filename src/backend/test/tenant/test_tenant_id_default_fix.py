"""Regression tests for the v2.5 ``tenant_id default=1`` leak.

The bug: ORM models declared ``tenant_id: int = Field(default=1, ...)``.
SQLModel filled the column with ``1`` at instantiation time, so the
framework's ``before_flush`` hook (which only auto-fills when the value
is ``None`` or ``0``) silently let child-tenant resources land on root.

The fix: change the Python default to ``None`` (Optional[int]). The hook
now auto-fills from the request's ``current_tenant_id`` ContextVar.

These tests use two parallel SQLModel test classes — one mimicking the
fixed model (default=None) and one mimicking the buggy model (default=1)
— so the fix's semantics are explicit and the regression is wired into
CI alongside the existing ``test_tenant_filter`` suite.
"""

import logging
import sys
from unittest.mock import MagicMock

import pytest
from sqlalchemy import Column, Integer, String, create_engine, text
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Session, select
from typing import Optional

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.config.multi_tenant import MultiTenantConf
from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    current_tenant_id,
    set_current_tenant_id,
)


# Mirror the lightweight pre-mock used by test_tenant_filter.py so this
# module can run independently of conftest.py side effects.
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
            _mock.settings.multi_tenant = MultiTenantConf(enabled=True)
        sys.modules[_m] = _mock


# ---------------------------------------------------------------------------
# Test-only models
# ---------------------------------------------------------------------------

class _FixedTenantItem(SQLModelSerializable, table=True):
    """Mirrors the post-fix model shape: tenant_id default=None."""
    __tablename__ = '_fixed_tenant_item'
    id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, primary_key=True, autoincrement=True),
    )
    name: str = Field(sa_column=Column(String(64), nullable=False))
    tenant_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, nullable=False,
                         server_default=text('1'), index=True),
    )


class _BuggyTenantItem(SQLModelSerializable, table=True):
    """Mirrors the pre-fix model shape: tenant_id default=1.

    Used as a control to prove the fix (and to keep the test honest if
    someone removes the before_flush mismatch warning).
    """
    __tablename__ = '_buggy_tenant_item'
    id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, primary_key=True, autoincrement=True),
    )
    name: str = Field(sa_column=Column(String(64), nullable=False))
    tenant_id: int = Field(
        default=1,
        sa_column=Column(Integer, nullable=False,
                         server_default=text('1'), index=True),
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def filter_engine():
    """Fresh SQLite engine with tenant filter events registered."""
    from bisheng.core.database import tenant_filter

    tenant_filter._initialized = False
    tenant_filter._tenant_aware_tables = set()

    engine = create_engine(
        'sqlite://',
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    _FixedTenantItem.__table__.create(engine, checkfirst=True)
    _BuggyTenantItem.__table__.create(engine, checkfirst=True)

    tenant_filter.register_tenant_filter_events()

    yield engine

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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPostFixBehavior:
    """default=None lets before_flush auto-fill from the ContextVar."""

    def test_fixed_model_inherits_child_tenant_on_insert(self, session):
        token = set_current_tenant_id(7)
        try:
            item = _FixedTenantItem(name='child-resource')
            assert item.tenant_id is None  # not yet flushed
            session.add(item)
            session.flush()
            assert item.tenant_id == 7, (
                'default=None must let before_flush auto-fill from '
                'current_tenant_id (=7).'
            )
        finally:
            current_tenant_id.reset(token)

    def test_explicit_tenant_id_is_respected(self, session):
        """Cross-tenant writes (admin-scope, migration scripts) still work."""
        token = set_current_tenant_id(7)
        try:
            with bypass_tenant_filter():
                item = _FixedTenantItem(name='cross-tenant', tenant_id=42)
                session.add(item)
                session.flush()
            assert item.tenant_id == 42
        finally:
            current_tenant_id.reset(token)

    def test_root_admin_default_root(self, session):
        """Root admins (tenant_id=1) write to root."""
        token = set_current_tenant_id(1)
        try:
            item = _FixedTenantItem(name='root-resource')
            session.add(item)
            session.flush()
            assert item.tenant_id == 1
        finally:
            current_tenant_id.reset(token)

    def test_select_isolates_child_from_root(self, session):
        """Sanity: child-tenant rows are invisible to root via do_orm_execute."""
        with bypass_tenant_filter():
            session.add(_FixedTenantItem(name='child', tenant_id=7))
            session.add(_FixedTenantItem(name='root', tenant_id=1))
            session.commit()

        token = set_current_tenant_id(7)
        try:
            rows = session.exec(select(_FixedTenantItem)).all()
            assert {r.name for r in rows} == {'child'}
        finally:
            current_tenant_id.reset(token)


class TestBuggyModelStillBuggy:
    """Reproduces the original bug to keep the regression honest."""

    def test_buggy_model_silently_falls_to_root(self, session, caplog):
        """Pre-fix shape: child-tenant context but obj already has 1 → stays 1."""
        token = set_current_tenant_id(7)
        try:
            with caplog.at_level(logging.WARNING,
                                 logger='bisheng.core.database.tenant_filter'):
                item = _BuggyTenantItem(name='leak')
                assert item.tenant_id == 1  # leaked default
                session.add(item)
                session.flush()
            assert item.tenant_id == 1, (
                'Buggy model proves the historical leak: explicit default=1 '
                'survives because before_flush only auto-fills None/0.'
            )
            mismatch_logs = [
                r for r in caplog.records
                if 'tenant_id mismatch on write' in r.getMessage()
            ]
            assert mismatch_logs, (
                'before_flush should now log a WARNING when the new object '
                'carries a tenant_id different from the request context.'
            )
        finally:
            current_tenant_id.reset(token)
