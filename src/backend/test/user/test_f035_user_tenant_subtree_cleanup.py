"""Tests for the F035 ``user_tenant`` residue cleanup migration.

Drives ``v2_5_1_f035_user_tenant_subtree_cleanup.upgrade`` against an
in-memory sqlite database with hand-built tables. The world has both
"clean" rows (primary dept inside the tenant subtree) and "phantom" rows
(primary dept outside the subtree but ``UserTenant.is_active=1``); the
migration must flip *only* the phantom rows to ``is_active=NULL``.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
import sqlalchemy as sa


_DDL = [
    """
    CREATE TABLE tenant (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_code VARCHAR(64) NOT NULL UNIQUE,
        tenant_name VARCHAR(128) NOT NULL,
        root_dept_id INTEGER,
        status VARCHAR(16) NOT NULL DEFAULT 'active',
        parent_tenant_id INTEGER
    )
    """,
    """
    CREATE TABLE department (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dept_id VARCHAR(64) NOT NULL UNIQUE,
        name VARCHAR(128) NOT NULL,
        parent_id INTEGER,
        tenant_id INTEGER NOT NULL DEFAULT 1,
        path VARCHAR(512) NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE TABLE user_department (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        department_id INTEGER NOT NULL,
        is_primary INTEGER DEFAULT 1
    )
    """,
    """
    CREATE TABLE user_tenant (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        tenant_id INTEGER NOT NULL,
        is_active INTEGER
    )
    """,
]


@pytest.fixture
def engine():
    eng = sa.create_engine('sqlite://')
    with eng.begin() as conn:
        for ddl in _DDL:
            conn.execute(sa.text(ddl))
    yield eng
    eng.dispose()


def _seed(conn) -> dict:
    """Seed:
      - Tenant 1 (root) root_dept=10 path='/10/'
      - Tenant 5 (child) root_dept=20 path='/10/20/'
      - dept 30 under tenant 5 (path '/10/20/30/')
      - dept 40 under tenant 1 sibling (path '/10/40/')
      - User A (uid=101): primary dept 20 → in tenant 5 subtree (CLEAN)
      - User B (uid=102): primary dept 40 → not in tenant 5 (PHANTOM if UT@5)
      - User C (uid=103): primary dept 30 → in tenant 5 subtree (CLEAN)
    Returns ids of the seeded user_tenant rows for assertion.
    """
    conn.execute(sa.text(
        "INSERT INTO tenant (id, tenant_code, tenant_name, root_dept_id) "
        "VALUES (1,'root','Root',10), (5,'child','Child',20)"
    ))
    conn.execute(sa.text(
        "INSERT INTO department (id, dept_id, name, parent_id, tenant_id, path) VALUES "
        "(10,'BS@root','root',NULL,1,'/10/'), "
        "(20,'BS@child','child',10,5,'/10/20/'), "
        "(30,'BS@sub','sub',20,5,'/10/20/30/'), "
        "(40,'BS@sib','sib',10,1,'/10/40/')"
    ))
    conn.execute(sa.text(
        "INSERT INTO user_department (user_id, department_id, is_primary) VALUES "
        "(101,20,1),(102,40,1),(103,30,1)"
    ))
    conn.execute(sa.text(
        "INSERT INTO user_tenant (id, user_id, tenant_id, is_active) VALUES "
        "(1,101,5,1),"   # CLEAN: A in subtree of 5
        "(2,102,5,1),"   # PHANTOM: B's primary dept 40 not in 5's subtree
        "(3,103,5,1),"   # CLEAN: C in subtree of 5
        "(4,102,1,1),"   # CLEAN: B's primary dept 40 IS in 1's subtree
        "(5,101,1,NULL)"  # historical row — must remain NULL
    ))
    return {'phantom_id': 2, 'clean_ids': [1, 3, 4], 'historical_id': 5}


def _run_upgrade(engine):
    """Invoke the migration's ``upgrade()`` against ``engine``.

    The migration uses ``alembic.op.get_bind()`` — we patch that to hand
    back our engine's connection so the SQL runs in our test transaction.
    """
    from bisheng.core.database.alembic.versions import (
        v2_5_1_f035_user_tenant_subtree_cleanup as mig,
    )
    with engine.begin() as conn:
        with patch.object(mig.op, 'get_bind', return_value=conn):
            mig.upgrade()


def test_phantom_row_flipped_to_null(engine):
    with engine.begin() as conn:
        ids = _seed(conn)
    _run_upgrade(engine)
    with engine.connect() as conn:
        row = conn.execute(sa.text(
            "SELECT is_active FROM user_tenant WHERE id = :id"
        ), {'id': ids['phantom_id']}).fetchone()
        assert row[0] is None


def test_clean_rows_unchanged(engine):
    with engine.begin() as conn:
        ids = _seed(conn)
    _run_upgrade(engine)
    with engine.connect() as conn:
        for cid in ids['clean_ids']:
            row = conn.execute(sa.text(
                "SELECT is_active FROM user_tenant WHERE id = :id"
            ), {'id': cid}).fetchone()
            assert row[0] == 1, f'clean row {cid} unexpectedly flipped'


def test_historical_null_row_untouched(engine):
    with engine.begin() as conn:
        ids = _seed(conn)
    _run_upgrade(engine)
    with engine.connect() as conn:
        row = conn.execute(sa.text(
            "SELECT is_active FROM user_tenant WHERE id = :id"
        ), {'id': ids['historical_id']}).fetchone()
        assert row[0] is None


def test_idempotent_rerun(engine):
    """Running upgrade twice must not change state after the first run."""
    with engine.begin() as conn:
        _seed(conn)
    _run_upgrade(engine)
    _run_upgrade(engine)
    with engine.connect() as conn:
        # Phantom remains NULL, clean remain 1.
        rows = conn.execute(sa.text(
            "SELECT id, is_active FROM user_tenant ORDER BY id"
        )).fetchall()
        by_id = {r[0]: r[1] for r in rows}
        assert by_id[2] is None
        assert by_id[1] == 1
        assert by_id[3] == 1
        assert by_id[4] == 1


def test_fallback_when_tenant_has_no_root_dept_id(engine):
    """Tenant without root_dept_id falls back to ``Department.tenant_id``.

    Phantom in this regime: UserTenant points at a tenant whose flat
    tenant_id has no matching primary dept for the user.
    """
    with engine.begin() as conn:
        # Tenant 7 has no root_dept_id.
        conn.execute(sa.text(
            "INSERT INTO tenant (id, tenant_code, tenant_name, root_dept_id) "
            "VALUES (7,'legacy','Legacy',NULL)"
        ))
        conn.execute(sa.text(
            "INSERT INTO department (id, dept_id, name, parent_id, tenant_id, path) "
            "VALUES (70,'BS@l','l',NULL,7,'/70/'), "
            "       (71,'BS@other','o',NULL,99,'/71/')"
        ))
        conn.execute(sa.text(
            "INSERT INTO user_department (user_id, department_id, is_primary) "
            "VALUES (701,70,1), (702,71,1)"
        ))
        conn.execute(sa.text(
            "INSERT INTO user_tenant (id, user_id, tenant_id, is_active) VALUES "
            "(10,701,7,1),"  # CLEAN: 701 has primary dept in tenant 7
            "(11,702,7,1)"   # PHANTOM: 702's primary dept is in tenant 99
        ))
    _run_upgrade(engine)
    with engine.connect() as conn:
        clean = conn.execute(sa.text(
            "SELECT is_active FROM user_tenant WHERE id = 10"
        )).fetchone()
        phantom = conn.execute(sa.text(
            "SELECT is_active FROM user_tenant WHERE id = 11"
        )).fetchone()
        assert clean[0] == 1
        assert phantom[0] is None
