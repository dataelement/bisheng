"""Tests for ``scripts/backfill_user_tenant_associations.py``.

This backfill was moved out of the startup flow (``_init_default_tenant``)
into a one-off script so the table-wide ``users``/``user_tenant`` scan no
longer runs on every boot. These tests drive the real ``run_backfill`` against
sync SQLite (faithful to the original startup logic) covering: backfilling
users with no row, activating orphan default rows, dry-run safety, and
idempotency.
"""

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, select

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

import scripts.backfill_user_tenant_associations as mod  # noqa: E402
from bisheng.database.models.tenant import Tenant, UserTenant  # noqa: E402
from test.fixtures.table_definitions import create_tables  # noqa: E402


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    create_tables(engine, "tenant", "user_tenant", "user")
    connection = engine.connect()
    transaction = connection.begin()
    sess = Session(bind=connection)
    yield sess
    sess.close()
    if transaction.is_active:
        transaction.rollback()
    connection.close()
    engine.dispose()


def _add_default_tenant(session):
    session.add(Tenant(id=1, tenant_code="default", tenant_name="Default Tenant", status="active"))
    session.commit()


def _add_user(session, user_id):
    # Raw insert: the fixture DDL is a subset of the current User model columns,
    # and run_backfill only ever SELECTs user_id, so a minimal row is enough.
    session.execute(
        text("INSERT INTO user (user_id, user_name, password) VALUES (:id, :n, 'x')"),
        {"id": user_id, "n": f"u{user_id}"},
    )
    session.commit()


def _active_rows(session):
    return session.exec(select(UserTenant).where(UserTenant.is_active == 1)).all()


class TestBackfillMissingRows:
    def test_user_without_row_gets_default_active_row(self, session):
        _add_default_tenant(session)
        _add_user(session, 1)

        stats = mod.run_backfill(session, apply=True)

        assert stats.backfilled == 1
        rows = _active_rows(session)
        assert len(rows) == 1
        row = rows[0]
        assert row.user_id == 1
        assert row.tenant_id == 1
        assert row.is_default == 1
        assert row.is_active == 1
        assert row.status == "active"

    def test_user_with_existing_row_is_untouched(self, session):
        _add_default_tenant(session)
        _add_user(session, 1)
        session.add(UserTenant(user_id=1, tenant_id=1, is_default=1, is_active=1, status="active"))
        session.commit()

        stats = mod.run_backfill(session, apply=True)

        assert stats.backfilled == 0
        assert len(_active_rows(session)) == 1


class TestActivateOrphanRows:
    def test_orphan_default_row_is_activated(self, session):
        _add_default_tenant(session)
        _add_user(session, 1)
        # Orphan: is_default=1 / status=active / is_active IS NULL, no active leaf.
        session.add(UserTenant(user_id=1, tenant_id=1, is_default=1, is_active=None, status="active"))
        session.commit()

        stats = mod.run_backfill(session, apply=True)

        # The user already has a (NULL) row, so it is not "backfilled" — it is activated.
        assert stats.backfilled == 0
        assert stats.activated == 1
        active = _active_rows(session)
        assert len(active) == 1
        assert active[0].user_id == 1

    def test_orphan_skipped_when_user_already_has_active_leaf(self, session):
        _add_default_tenant(session)
        _add_user(session, 1)
        # User has a current active leaf on another tenant + a stale NULL default row.
        session.add(UserTenant(user_id=1, tenant_id=7, is_default=0, is_active=1, status="active"))
        session.add(UserTenant(user_id=1, tenant_id=1, is_default=1, is_active=None, status="active"))
        session.commit()

        stats = mod.run_backfill(session, apply=True)

        assert stats.activated == 0
        # The pre-existing active leaf on tenant 7 is left intact; nothing promoted.
        active = _active_rows(session)
        assert len(active) == 1
        assert active[0].tenant_id == 7


class TestDryRun:
    def test_dry_run_writes_nothing(self, session):
        _add_default_tenant(session)
        _add_user(session, 1)
        _add_user(session, 2)

        stats = mod.run_backfill(session, apply=False)

        assert stats.backfilled == 2  # would-be count is reported
        # ...but nothing was written.
        assert session.exec(select(UserTenant)).all() == []

    def test_dry_run_creates_no_tenant(self, session):
        # No default tenant in the DB yet.
        _add_user(session, 1)

        stats = mod.run_backfill(session, apply=False)

        assert stats.tenant_created is True
        assert session.exec(select(Tenant)).all() == []


class TestIdempotency:
    def test_second_run_is_noop(self, session):
        _add_default_tenant(session)
        _add_user(session, 1)
        _add_user(session, 2)

        first = mod.run_backfill(session, apply=True)
        assert first.backfilled == 2

        second = mod.run_backfill(session, apply=True)
        assert second.backfilled == 0
        assert second.activated == 0
        assert len(_active_rows(session)) == 2


class TestEnsureDefaultTenant:
    def test_missing_default_tenant_is_created_on_apply(self, session):
        _add_user(session, 1)

        stats = mod.run_backfill(session, apply=True)

        assert stats.tenant_created is True
        tenant = session.exec(select(Tenant).where(Tenant.id == 1)).first()
        assert tenant is not None
        assert tenant.tenant_code == "default"
        # And the user got backfilled against the freshly-created tenant.
        assert stats.backfilled == 1
