"""Tests for F011 UserTenant unique-leaf semantics.

Verifies:
- ORM-level insertion of ``is_active`` NULL/1 values.
- MySQL's "multiple NULL allowed in unique index" behaviour on SQLite
  (SQLite honours SQL standard here — same semantics as MySQL).
- ``uk_user_active`` rejects two active rows for the same user_id.

DAO async methods (adeactivate/aactivate) are covered by T10 integration
tests end-to-end. This file focuses on the DDL + ORM field contract.
"""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, select

from bisheng.database.models.tenant import UserTenant


@pytest.fixture(scope='module')
def dao_engine():
    """SQLite engine with v2.5.1 extended user_tenant DDL (uk_user_active)."""
    engine = create_engine(
        'sqlite://',
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS user_tenant (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                tenant_id INTEGER NOT NULL,
                is_default INTEGER NOT NULL DEFAULT 0,
                status VARCHAR(16) NOT NULL DEFAULT 'active',
                is_active INTEGER,
                last_access_time DATETIME,
                join_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
            )
        """))
        # SQLite: UNIQUE index treats NULLs as distinct (same as MySQL InnoDB)
        conn.execute(text(
            'CREATE UNIQUE INDEX uk_user_active ON user_tenant (user_id, is_active)'
        ))
    yield engine
    engine.dispose()


@pytest.fixture()
def session(dao_engine):
    connection = dao_engine.connect()
    transaction = connection.begin()
    sess = Session(bind=connection)
    yield sess
    sess.close()
    if transaction.is_active:
        transaction.rollback()
    connection.close()


# =========================================================================
# ORM field contract
# =========================================================================

class TestIsActiveField:

    def test_is_active_defaults_to_null(self, session):
        ut = UserTenant(user_id=1, tenant_id=1, is_default=1)
        session.add(ut)
        session.commit()
        session.refresh(ut)
        assert ut.is_active is None

    def test_is_active_accepts_one(self, session):
        ut = UserTenant(user_id=2, tenant_id=1, is_default=1, is_active=1)
        session.add(ut)
        session.commit()
        session.refresh(ut)
        assert ut.is_active == 1

    def test_is_active_accepts_null_explicit(self, session):
        ut = UserTenant(user_id=3, tenant_id=1, is_default=0, is_active=None)
        session.add(ut)
        session.commit()
        session.refresh(ut)
        assert ut.is_active is None


# =========================================================================
# uk_user_active unique constraint semantics (AC-09)
# =========================================================================

class TestUkUserActive:

    def test_second_active_row_rejected(self, session):
        """AC-09: two is_active=1 rows for the same user → IntegrityError."""
        session.add(UserTenant(user_id=10, tenant_id=1, is_active=1))
        session.commit()

        session.add(UserTenant(user_id=10, tenant_id=2, is_active=1))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    def test_multiple_null_rows_allowed(self, session):
        """NULL trick: unlimited history rows per user are permitted."""
        session.add(UserTenant(user_id=20, tenant_id=1, is_active=None))
        session.add(UserTenant(user_id=20, tenant_id=2, is_active=None))
        session.add(UserTenant(user_id=20, tenant_id=3, is_active=None))
        session.commit()

        rows = session.exec(
            select(UserTenant).where(UserTenant.user_id == 20)
        ).all()
        assert len(rows) == 3
        assert all(r.is_active is None for r in rows)

    def test_one_active_plus_many_null_allowed(self, session):
        """Unique-leaf shape: 1 active + N history is the common pattern."""
        session.add(UserTenant(user_id=30, tenant_id=1, is_active=1))
        session.add(UserTenant(user_id=30, tenant_id=2, is_active=None))
        session.add(UserTenant(user_id=30, tenant_id=3, is_active=None))
        session.commit()

        active = session.exec(
            select(UserTenant).where(
                UserTenant.user_id == 30,
                UserTenant.is_active == 1,
            )
        ).all()
        assert len(active) == 1
        assert active[0].tenant_id == 1

        history = session.exec(
            select(UserTenant).where(
                UserTenant.user_id == 30,
                UserTenant.is_active.is_(None),
            )
        ).all()
        assert len(history) == 2


# =========================================================================
# Equivalent SELECT for aget_active_user_tenant
# =========================================================================

class TestAgetActiveUserTenantSelect:

    def test_returns_active_when_present(self, session):
        session.add(UserTenant(user_id=40, tenant_id=1, is_active=None))
        session.add(UserTenant(user_id=40, tenant_id=2, is_active=1))
        session.commit()

        result = session.exec(
            select(UserTenant).where(
                UserTenant.user_id == 40,
                UserTenant.is_active == 1,
            )
        ).first()
        assert result is not None
        assert result.tenant_id == 2

    def test_returns_none_when_all_history(self, session):
        session.add(UserTenant(user_id=50, tenant_id=1, is_active=None))
        session.add(UserTenant(user_id=50, tenant_id=2, is_active=None))
        session.commit()

        result = session.exec(
            select(UserTenant).where(
                UserTenant.user_id == 50,
                UserTenant.is_active == 1,
            )
        ).first()
        assert result is None
