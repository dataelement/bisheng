"""Tests for F011 Alembic migration helpers (v2_5_1_f011_tenant_tree).

The migration's DDL (ALTER TABLE ... ADD COLUMN / DROP INDEX / ADD INDEX)
is exercised by ``alembic upgrade head`` in CI/manual QA, but the
non-trivial **business logic** — Root tenant backfill, multi-active
UserTenant dedup — needs unit coverage. These helpers are extracted as
pure functions taking a live SQLAlchemy connection, making them directly
callable against a SQLite test engine.

Following SDD Test-First from T06 onward: written BEFORE the migration
implementation; must fail first, then pass once helpers exist.
"""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool


@pytest.fixture()
def mysql_like_engine():
    """SQLite engine with v2.5.0 baseline tenant + user_tenant tables.

    Mirrors the schema at the point the migration starts running.
    """
    engine = create_engine(
        'sqlite://',
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE tenant (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_code VARCHAR(64) NOT NULL UNIQUE,
                tenant_name VARCHAR(128) NOT NULL,
                status VARCHAR(16) NOT NULL DEFAULT 'active',
                parent_tenant_id INTEGER,
                share_default_to_children INTEGER NOT NULL DEFAULT 1,
                create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE TABLE user_tenant (
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
    yield engine
    engine.dispose()


# =========================================================================
# Root backfill helper (spec §5.1 "Root Tenant 回填")
# =========================================================================

class TestEnsureRootTenantShape:

    def test_existing_root_gets_tree_fields_set(self, mysql_like_engine):
        """When tenant id=1 already exists (F001 inserted it), F011 only
        fills in parent_tenant_id=NULL and share_default_to_children=1."""
        from bisheng.core.database.alembic_helpers.f011 import ensure_root_tenant_shape

        with mysql_like_engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO tenant (id, tenant_code, tenant_name, status, "
                "parent_tenant_id, share_default_to_children) "
                "VALUES (1, 'default', 'Default', 'active', 99, 0)"
            ))  # Simulate stray values

            ensure_root_tenant_shape(conn)

            row = conn.execute(text(
                "SELECT parent_tenant_id, share_default_to_children "
                "FROM tenant WHERE id = 1"
            )).one()
            assert row[0] is None
            assert row[1] == 1

    def test_missing_root_is_created(self, mysql_like_engine):
        """If tenant table is empty (non-standard deploy), backstop INSERTs Root."""
        from bisheng.core.database.alembic_helpers.f011 import ensure_root_tenant_shape

        with mysql_like_engine.begin() as conn:
            ensure_root_tenant_shape(conn)

            row = conn.execute(text(
                "SELECT id, tenant_code, parent_tenant_id, share_default_to_children "
                "FROM tenant WHERE id = 1"
            )).one()
            assert row[0] == 1
            assert row[1] == 'default'
            assert row[2] is None
            assert row[3] == 1


# =========================================================================
# user_tenant multi-active dedup helper
# =========================================================================

class TestDeduplicateMultiActiveUserTenants:

    def test_single_active_row_unchanged(self, mysql_like_engine):
        from bisheng.core.database.alembic_helpers.f011 import (
            backfill_is_active,
            deduplicate_multi_active_user_tenants,
        )

        with mysql_like_engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO user_tenant (user_id, tenant_id, is_default, status) "
                "VALUES (1, 1, 1, 'active')"
            ))
            backfill_is_active(conn)
            deduplicate_multi_active_user_tenants(conn)

            rows = conn.execute(text(
                "SELECT tenant_id, is_active FROM user_tenant WHERE user_id = 1"
            )).all()
            assert len(rows) == 1
            assert rows[0][1] == 1  # is_active=1

    def test_multi_active_keeps_latest_access_time(self, mysql_like_engine):
        """When same user has multiple active rows, keep the one with
        the most recent last_access_time; demote the rest to NULL."""
        from bisheng.core.database.alembic_helpers.f011 import (
            backfill_is_active,
            deduplicate_multi_active_user_tenants,
        )

        with mysql_like_engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO user_tenant (user_id, tenant_id, is_default, status, last_access_time) "
                "VALUES (5, 1, 1, 'active', '2026-01-01 10:00:00')"
            ))
            conn.execute(text(
                "INSERT INTO user_tenant (user_id, tenant_id, is_default, status, last_access_time) "
                "VALUES (5, 2, 1, 'active', '2026-03-01 10:00:00')"  # newest
            ))
            conn.execute(text(
                "INSERT INTO user_tenant (user_id, tenant_id, is_default, status, last_access_time) "
                "VALUES (5, 3, 1, 'active', '2026-02-01 10:00:00')"
            ))
            backfill_is_active(conn)
            deduplicate_multi_active_user_tenants(conn)

            rows = conn.execute(text(
                "SELECT tenant_id, is_active FROM user_tenant "
                "WHERE user_id = 5 ORDER BY tenant_id"
            )).all()
            active = [(tid, ia) for tid, ia in rows if ia == 1]
            history = [(tid, ia) for tid, ia in rows if ia is None]
            assert len(active) == 1
            assert active[0][0] == 2  # tenant with newest access
            assert len(history) == 2

    def test_only_primary_default_becomes_active(self, mysql_like_engine):
        """backfill_is_active sets is_active=1 only where status='active' AND is_default=1."""
        from bisheng.core.database.alembic_helpers.f011 import backfill_is_active

        with mysql_like_engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO user_tenant (user_id, tenant_id, is_default, status) "
                "VALUES (7, 1, 1, 'active')"
            ))
            conn.execute(text(
                "INSERT INTO user_tenant (user_id, tenant_id, is_default, status) "
                "VALUES (7, 2, 0, 'active')"  # non-default
            ))
            conn.execute(text(
                "INSERT INTO user_tenant (user_id, tenant_id, is_default, status) "
                "VALUES (7, 3, 1, 'disabled')"  # not active status
            ))
            backfill_is_active(conn)

            rows = conn.execute(text(
                "SELECT tenant_id, is_active FROM user_tenant "
                "WHERE user_id = 7 ORDER BY tenant_id"
            )).all()
            by_tenant = {tid: ia for tid, ia in rows}
            assert by_tenant == {1: 1, 2: None, 3: None}
