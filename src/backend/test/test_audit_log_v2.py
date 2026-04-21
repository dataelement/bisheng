"""Tests for F011 AuditLog v2 structured columns + SELECT semantics.

Exercises the schema extension (7 new columns) via direct INSERT/SELECT
through a self-contained SQLite engine. The async ``AuditLogDao.ainsert_v2``
/``aget_by_action`` / ``aget_visible_for_child_admin`` wrappers are thin
transaction/bypass shims around these exact statements — integration
coverage comes from T10 API tests.
"""

import json

import pytest
from sqlalchemy import create_engine, func, or_, text
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, select


# NOTE: importing AuditLog through the ORM pulls the full bisheng stack
# (core.context → core.config → celery). Pytest's conftest pre-mocks this
# chain; running this file via `pytest` is required, not direct `python -c`.
from bisheng.database.models.audit_log import AuditLog


@pytest.fixture(scope='module')
def dao_engine():
    """SQLite engine with v2.5.1 extended auditlog DDL (F011 fields added)."""
    engine = create_engine(
        'sqlite://',
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS auditlog (
                id VARCHAR(255) PRIMARY KEY,
                operator_id INTEGER NOT NULL,
                operator_name VARCHAR(255),
                group_ids JSON,
                system_id VARCHAR(64),
                event_type VARCHAR(64),
                object_type VARCHAR(64),
                object_id VARCHAR(64),
                object_name TEXT,
                note TEXT,
                ip_address VARCHAR(64),
                tenant_id INTEGER,
                operator_tenant_id INTEGER,
                action VARCHAR(64),
                target_type VARCHAR(32),
                target_id VARCHAR(64),
                reason TEXT,
                metadata JSON,
                create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
            )
        """))
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


def _insert_v2(session, **kwargs):
    """Shortcut mirroring AuditLogDao.ainsert_v2."""
    defaults = dict(
        tenant_id=None, operator_id=1, operator_tenant_id=1,
        action='test.noop', target_type=None, target_id=None,
        reason=None, audit_metadata=None,
    )
    defaults.update(kwargs)
    entry = AuditLog(**defaults)
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


# =========================================================================
# Structured column tests
# =========================================================================

class TestAuditLogV2Columns:

    def test_ainsert_v2_persists_structured_fields(self, session):
        entry = _insert_v2(
            session,
            tenant_id=5, operator_id=42, operator_tenant_id=1,
            action='tenant.mount',
            target_type='tenant', target_id='5',
            reason='group mount',
            audit_metadata={'dept_id': 10, 'tenant_code': 'acme'},
        )
        fetched = session.exec(
            select(AuditLog).where(AuditLog.id == entry.id)
        ).one()
        assert fetched.tenant_id == 5
        assert fetched.operator_tenant_id == 1
        assert fetched.action == 'tenant.mount'
        assert fetched.target_type == 'tenant'
        assert fetched.target_id == '5'
        assert fetched.reason == 'group mount'
        assert fetched.audit_metadata == {'dept_id': 10, 'tenant_code': 'acme'}

    def test_metadata_json_roundtrip(self, session):
        payload = {
            'old_quota': 10, 'new_quota': 20,
            'affected_ids': [1, 2, 3],
            'nested': {'from_scope': 1, 'to_scope': 2},
        }
        entry = _insert_v2(session, action='quota.update', audit_metadata=payload)
        fetched = session.exec(
            select(AuditLog).where(AuditLog.id == entry.id)
        ).one()
        assert fetched.audit_metadata == payload

    def test_legacy_fields_still_writable(self, session):
        """Legacy v2.5.0 callers keep writing system_id/event_type/object_*.

        New columns remain NULL. Two writer paths coexist without conflict.
        """
        entry = AuditLog(
            operator_id=99, operator_name='legacy-user',
            system_id='CHAT', event_type='CREATE_CHAT',
            object_type='chat', object_id='abc123',
            group_ids=[1, 2],
        )
        session.add(entry)
        session.commit()
        session.refresh(entry)

        fetched = session.exec(
            select(AuditLog).where(AuditLog.id == entry.id)
        ).one()
        assert fetched.event_type == 'CREATE_CHAT'
        assert fetched.action is None
        assert fetched.tenant_id is None


# =========================================================================
# aget_by_action SELECT semantics
# =========================================================================

class TestAgetByActionSelect:

    def test_filters_by_action(self, session):
        _insert_v2(session, action='tenant.mount', tenant_id=2)
        _insert_v2(session, action='tenant.mount', tenant_id=3)
        _insert_v2(session, action='quota.update', tenant_id=2)

        rows = session.exec(
            select(AuditLog).where(AuditLog.action == 'tenant.mount')
        ).all()
        assert len(rows) == 2
        assert all(r.action == 'tenant.mount' for r in rows)

    def test_combined_action_and_tenant(self, session):
        _insert_v2(session, action='tenant.mount', tenant_id=2)
        _insert_v2(session, action='tenant.mount', tenant_id=3)

        rows = session.exec(
            select(AuditLog).where(
                AuditLog.action == 'tenant.mount',
                AuditLog.tenant_id == 2,
            )
        ).all()
        assert len(rows) == 1
        assert rows[0].tenant_id == 2


# =========================================================================
# aget_visible_for_child_admin SELECT semantics (spec §5.4 visibility rule)
# =========================================================================

class TestVisibleForChildAdminSelect:

    def test_includes_rows_tied_by_either_tenant(self, session):
        """Child Admin of tenant=5 sees:
          - rows where tenant_id = 5 (resource in their tenant), OR
          - rows where operator_tenant_id = 5 (operator inside their tenant).
        """
        # (1) Resource in tenant 5, operator in tenant 5 — visible.
        _insert_v2(session, tenant_id=5, operator_tenant_id=5, action='a.1')
        # (2) Resource in tenant 5, operator is global super (scope=1) — visible.
        _insert_v2(session, tenant_id=5, operator_tenant_id=1, action='a.2')
        # (3) Resource in tenant 1 (Root), operator scoped to tenant 5 — visible
        #     (super did something targeting Root but logged within scope 5).
        _insert_v2(session, tenant_id=1, operator_tenant_id=5, action='a.3')
        # (4) Unrelated to tenant 5 — NOT visible.
        _insert_v2(session, tenant_id=2, operator_tenant_id=2, action='a.4')

        rows = session.exec(
            select(AuditLog).where(
                or_(
                    AuditLog.tenant_id == 5,
                    AuditLog.operator_tenant_id == 5,
                )
            )
        ).all()
        actions = {r.action for r in rows}
        assert actions == {'a.1', 'a.2', 'a.3'}

    def test_count_matches_rows(self, session):
        for i in range(3):
            _insert_v2(session, tenant_id=7, operator_tenant_id=7, action=f'c.{i}')
        for i in range(2):
            _insert_v2(session, tenant_id=9, operator_tenant_id=9, action=f'c.other.{i}')

        predicate = or_(
            AuditLog.tenant_id == 7,
            AuditLog.operator_tenant_id == 7,
        )
        total = session.exec(
            select(func.count()).select_from(AuditLog).where(predicate)
        ).one()
        rows = session.exec(select(AuditLog).where(predicate)).all()
        assert total == len(rows) == 3
