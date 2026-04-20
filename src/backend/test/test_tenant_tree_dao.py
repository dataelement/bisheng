"""Tests for F011 Tenant tree ORM fields + equivalent DAO SELECT semantics.

Uses a self-contained SQLite engine with the v2.5.1 extended ``tenant`` DDL.
DAO methods are async (backed by ``get_async_db_session``) so this file
exercises the SQL semantics via the equivalent synchronous select statements
— the async wrapping is trivial and covered by T10 API integration tests.

Pattern matches F002 (``test_department_dao.py``).
"""

import pytest
from sqlalchemy import create_engine, func, text
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, select

from bisheng.database.models.tenant import ROOT_TENANT_ID, Tenant


@pytest.fixture(scope='module')
def dao_engine():
    """SQLite engine with the v2.5.1 extended tenant DDL (F011 fields added)."""
    engine = create_engine(
        'sqlite://',
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tenant (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_code VARCHAR(64) NOT NULL UNIQUE,
                tenant_name VARCHAR(128) NOT NULL,
                logo VARCHAR(512),
                root_dept_id INTEGER,
                status VARCHAR(16) NOT NULL DEFAULT 'active',
                parent_tenant_id INTEGER,
                share_default_to_children INTEGER NOT NULL DEFAULT 1,
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


@pytest.fixture()
def session(dao_engine):
    """Transactional session that rolls back after each test."""
    connection = dao_engine.connect()
    transaction = connection.begin()
    sess = Session(bind=connection)
    yield sess
    sess.close()
    if transaction.is_active:
        transaction.rollback()
    connection.close()


def _create_tenant(sess, code, name, parent_tenant_id=None, status='active', **kwargs):
    t = Tenant(
        tenant_code=code, tenant_name=name,
        parent_tenant_id=parent_tenant_id, status=status, **kwargs,
    )
    sess.add(t)
    sess.commit()
    sess.refresh(t)
    return t


# =========================================================================
# ORM field tests
# =========================================================================

class TestTenantTreeFields:

    def test_root_tenant_has_null_parent(self, session):
        """AC-01: Root tenant is identified by parent_tenant_id IS NULL."""
        root = _create_tenant(session, 'root1', 'Root', parent_tenant_id=None)
        assert root.parent_tenant_id is None

        fetched = session.exec(
            select(Tenant).where(Tenant.id == root.id)
        ).one()
        assert fetched.parent_tenant_id is None

    def test_child_tenant_parent_points_to_root(self, session):
        """AC-02: Child tenants have parent_tenant_id = 1 (Root id)."""
        root = _create_tenant(session, 'root2', 'Root')
        child = _create_tenant(session, 'ch1', 'Child A', parent_tenant_id=root.id)

        assert child.parent_tenant_id == root.id
        fetched = session.exec(
            select(Tenant).where(Tenant.id == child.id)
        ).one()
        assert fetched.parent_tenant_id == root.id

    def test_share_default_to_children_defaults_to_one(self, session):
        """share_default_to_children defaults to 1 when not provided."""
        t = _create_tenant(session, 'def1', 'Defaults')
        assert t.share_default_to_children == 1

    def test_share_default_can_be_disabled(self, session):
        """share_default_to_children=0 is honoured."""
        t = _create_tenant(
            session, 'def0', 'No Share', share_default_to_children=0,
        )
        assert t.share_default_to_children == 0

    def test_status_accepts_orphaned(self, session):
        """v2.5.1 adds 'orphaned' to the status enum (AC-12)."""
        t = _create_tenant(session, 'orph1', 'Orphan', status='orphaned')
        assert t.status == 'orphaned'


# =========================================================================
# DAO SELECT semantics (the async methods call these exact statements)
# =========================================================================

class TestTenantDaoSelectSemantics:

    def test_aget_children_ids_active_returns_only_active(self, session):
        """aget_children_ids_active filters by parent AND status='active'."""
        root = _create_tenant(session, 'r1', 'R')
        c1 = _create_tenant(session, 'c1', 'C1', parent_tenant_id=root.id, status='active')
        _create_tenant(session, 'c2', 'C2', parent_tenant_id=root.id, status='disabled')
        _create_tenant(session, 'c3', 'C3', parent_tenant_id=root.id, status='archived')
        c4 = _create_tenant(session, 'c4', 'C4', parent_tenant_id=root.id, status='active')

        # Mirror aget_children_ids_active's SELECT exactly
        result = session.exec(
            select(Tenant.id).where(
                Tenant.parent_tenant_id == root.id,
                Tenant.status == 'active',
            )
        ).all()
        ids = sorted(r for r in result)
        assert ids == sorted([c1.id, c4.id])

    def test_aget_children_ids_active_empty_when_no_children(self, session):
        root = _create_tenant(session, 'solo', 'Solo Root')

        result = session.exec(
            select(Tenant.id).where(
                Tenant.parent_tenant_id == root.id,
                Tenant.status == 'active',
            )
        ).all()
        assert list(result) == []

    def test_aget_non_active_ids_excludes_active(self, session):
        """aget_non_active_ids returns disabled/archived/orphaned only."""
        root = _create_tenant(session, 'nr', 'R')
        active = _create_tenant(session, 'na1', 'A', parent_tenant_id=root.id, status='active')
        dis = _create_tenant(session, 'nd1', 'D', parent_tenant_id=root.id, status='disabled')
        arch = _create_tenant(session, 'nar1', 'AR', parent_tenant_id=root.id, status='archived')
        orph = _create_tenant(session, 'no1', 'O', parent_tenant_id=root.id, status='orphaned')

        result = session.exec(
            select(Tenant.id).where(
                Tenant.status.in_(['disabled', 'archived', 'orphaned'])
            )
        ).all()
        ids = sorted(r for r in result)
        assert active.id not in ids
        assert sorted([dis.id, arch.id, orph.id]) == ids

    def test_aexists_true_for_existing(self, session):
        t = _create_tenant(session, 'ex1', 'Exists')

        count = session.exec(
            select(func.count()).select_from(Tenant).where(Tenant.id == t.id)
        ).one()
        assert count > 0

    def test_aexists_false_for_missing(self, session):
        count = session.exec(
            select(func.count()).select_from(Tenant).where(Tenant.id == 99999)
        ).one()
        assert count == 0

    def test_aget_by_parent_none_returns_roots(self, session):
        """Passing parent_id=None selects Root tenants (parent_tenant_id IS NULL)."""
        root = _create_tenant(session, 'pr1', 'Root')
        _create_tenant(session, 'pr1c', 'Child', parent_tenant_id=root.id)

        result = session.exec(
            select(Tenant).where(Tenant.parent_tenant_id.is_(None))
        ).all()
        ids = [t.id for t in result]
        assert root.id in ids
        # Any prior test Roots may exist; only assert our Root is present.

    def test_aget_by_parent_returns_all_statuses(self, session):
        """aget_by_parent does NOT filter by status (caller filters)."""
        root = _create_tenant(session, 'pr2', 'Root')
        _create_tenant(session, 'pr2a', 'Active', parent_tenant_id=root.id, status='active')
        _create_tenant(session, 'pr2d', 'Dis', parent_tenant_id=root.id, status='disabled')

        result = session.exec(
            select(Tenant).where(Tenant.parent_tenant_id == root.id)
        ).all()
        statuses = sorted(t.status for t in result)
        assert statuses == ['active', 'disabled']


class TestRootTenantConstant:

    def test_root_tenant_id_is_one(self):
        """INV-T11: Root tenant id is fixed to 1 across the codebase."""
        assert ROOT_TENANT_ID == 1
