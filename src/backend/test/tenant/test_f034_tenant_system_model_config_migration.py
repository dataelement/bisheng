"""F034 alembic migration integration test — fresh-DB upgrade verify.

Drives ``upgrade()`` / ``downgrade()`` of
``v2_5_1_f034_tenant_system_model_config.py`` against a real sqlite
in-memory engine via alembic's ``MigrationContext`` + ``Operations``
proxy. Scenarios:

  * fresh install (no legacy ``config`` table) — upgrade is a no-op
    on backfill, table is created                           [AC-25 partial]
  * legacy config has all 5 + 2 unrelated keys —
    backfill copies exactly the 5 to tenant_id=1            [AC-25]
  * upgrade rerun — INSERT IGNORE / OR IGNORE keeps row
    counts stable, no duplicate-create error                [AC-28]
  * downgrade drops only the new table; legacy config 5
    rows untouched (rollback anchor preserved)              [AD-06]
  * SQLModel.create_all path — table already exists,
    upgrade skips create_table and still runs backfill      [fresh-install path]
  * bind value updates pre-empted by INSERT IGNORE — old
    rows are NOT overwritten if they exist                  [AC-28 corollary]

Sqlite dialect is exercised via the dialect-aware ``INSERT OR IGNORE``
branch in F034. The MySQL ``INSERT IGNORE`` path is reached in
production end-to-end tests (out of scope for this unit-level run).
"""
import importlib.util
from pathlib import Path
from typing import Iterator

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


_F034_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / 'bisheng/core/database/alembic/versions/v2_5_1_f034_tenant_system_model_config.py'
)


def _load_f034_module():
    """Load F034 as an isolated module so the alembic ``op`` proxy
    binds to the correct context for each test invocation.
    """
    spec = importlib.util.spec_from_file_location('f034_under_test', _F034_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def engine() -> Iterator[Engine]:
    eng = sa.create_engine('sqlite://')
    yield eng
    eng.dispose()


def _create_legacy_config_table(connection) -> None:
    """Mirror the v2.5.0 ``config`` table shape just enough for F034
    backfill to find and copy from it."""
    connection.execute(text(
        """
        CREATE TABLE config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            "key" VARCHAR(255) UNIQUE NOT NULL,
            value TEXT,
            comment VARCHAR(255),
            create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
            update_time DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    ))


def _seed_config_rows(connection, rows: list[tuple[str, str]]) -> None:
    for key, value in rows:
        connection.execute(
            text('INSERT INTO config ("key", value) VALUES (:k, :v)'),
            {'k': key, 'v': value},
        )


def _run_upgrade(engine: Engine) -> None:
    """Apply F034.upgrade() inside a fresh op proxy context."""
    f034 = _load_f034_module()
    with engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            f034.upgrade()


def _run_downgrade(engine: Engine) -> None:
    f034 = _load_f034_module()
    with engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            f034.downgrade()


def _table_exists(engine: Engine, table: str) -> bool:
    insp = inspect(engine)
    return table in insp.get_table_names()


def _columns(engine: Engine, table: str) -> dict[str, sa.types.TypeEngine]:
    insp = inspect(engine)
    return {c['name']: c['type'] for c in insp.get_columns(table)}


def _row_count(engine: Engine, table: str) -> int:
    with engine.connect() as conn:
        return conn.execute(text(f'SELECT COUNT(*) FROM {table}')).scalar() or 0


# --- 1) fresh install --------------------------------------------------------


def test_upgrade_on_fresh_db_creates_table_without_backfill(engine: Engine):
    """No legacy ``config`` table → F034 creates the new table and
    silently skips backfill (no error)."""
    _run_upgrade(engine)

    assert _table_exists(engine, 'tenant_system_model_config')
    cols = _columns(engine, 'tenant_system_model_config')
    # Schema columns per spec §5.1 + ORM file.
    expected_cols = {
        'id', 'tenant_id', 'key', 'value', 'is_shared_to_children',
        'create_time', 'update_time',
    }
    assert expected_cols.issubset(cols.keys()), (
        f'Missing columns: {expected_cols - cols.keys()}'
    )
    # Backfill no-op: no row written.
    assert _row_count(engine, 'tenant_system_model_config') == 0


def test_upgrade_on_fresh_db_creates_unique_constraint_on_tenant_key(engine: Engine):
    _run_upgrade(engine)
    insp = inspect(engine)
    uniques = insp.get_unique_constraints('tenant_system_model_config')
    assert any(
        sorted(u['column_names']) == ['key', 'tenant_id']
        for u in uniques
    ), f'expected uq(tenant_id, key); got {uniques}'


# --- 2) backfill from legacy config -----------------------------------------


_FIVE_KEYS = (
    'knowledge_llm', 'assistant_llm', 'evaluation_llm',
    'workflow_llm', 'linsight_llm',
)


def test_upgrade_backfills_exactly_the_five_keys(engine: Engine):
    """AC-25: legacy config has all 5 keys + 2 unrelated keys → only the 5
    F022-managed keys are copied to tenant_id=1; unrelated keys (e.g.
    ``home_tags``) are left in ``config`` and NOT copied."""
    with engine.begin() as conn:
        _create_legacy_config_table(conn)
        _seed_config_rows(conn, [
            ('knowledge_llm', '{"embedding_model_id": 12}'),
            ('assistant_llm', '{"llm_list": []}'),
            ('evaluation_llm', '{"model_id": 7}'),
            ('workflow_llm', '{"model_id": 8}'),
            ('linsight_llm', '{"task_model": {"id": 9}}'),
            ('home_tags', '[{"id": 1}]'),       # not F022-managed
            ('web_config', '{"theme": "dark"}'),  # not F022-managed
        ])

    _run_upgrade(engine)

    # Exactly 5 rows, all tenant_id=1, keys from the F022 set.
    with engine.connect() as conn:
        rows = conn.execute(text(
            'SELECT tenant_id, "key", value FROM tenant_system_model_config '
            'ORDER BY "key"'
        )).fetchall()
    assert len(rows) == 5
    assert all(r.tenant_id == 1 for r in rows)
    assert {r.key for r in rows} == set(_FIVE_KEYS)
    # Spot-check value preserved verbatim.
    knowledge_row = next(r for r in rows if r.key == 'knowledge_llm')
    assert knowledge_row.value == '{"embedding_model_id": 12}'


def test_upgrade_skips_keys_with_empty_value(engine: Engine):
    """Legacy rows with NULL or empty-string value should not produce
    backfill rows — the WHERE c.value IS NOT NULL AND c.value <> ''
    filter prevents bogus '' inheritance."""
    with engine.begin() as conn:
        _create_legacy_config_table(conn)
        _seed_config_rows(conn, [
            ('knowledge_llm', ''),                      # empty
            ('assistant_llm', '{"llm_list": []}'),      # populated
        ])
        # NULL value via direct SQL (text bindparam can't pass NULL safely
        # through positional in all sqlalchemy versions).
        conn.execute(
            text('INSERT INTO config ("key", value) VALUES (:k, NULL)'),
            {'k': 'evaluation_llm'},
        )

    _run_upgrade(engine)

    with engine.connect() as conn:
        keys = [r.key for r in conn.execute(text(
            'SELECT "key" FROM tenant_system_model_config'
        )).fetchall()]
    assert keys == ['assistant_llm']


# --- 3) idempotency / rerun --------------------------------------------------


def test_upgrade_rerun_is_idempotent(engine: Engine):
    """AC-28: second upgrade does not duplicate rows nor error
    on the existing table."""
    with engine.begin() as conn:
        _create_legacy_config_table(conn)
        _seed_config_rows(conn, [(k, '{"v": 1}') for k in _FIVE_KEYS])

    _run_upgrade(engine)
    first_count = _row_count(engine, 'tenant_system_model_config')

    # Second upgrade — no error, no duplicates.
    _run_upgrade(engine)
    second_count = _row_count(engine, 'tenant_system_model_config')

    assert first_count == 5
    assert second_count == 5


def test_upgrade_rerun_does_not_overwrite_existing_value(engine: Engine):
    """AC-28 corollary: INSERT (OR) IGNORE means an admin who already
    edited a Child row keeps their value — the rerun must not
    silently restore Root's snapshot."""
    with engine.begin() as conn:
        _create_legacy_config_table(conn)
        _seed_config_rows(conn, [('knowledge_llm', '{"v": "ROOT"}')])

    _run_upgrade(engine)

    # Simulate an operator edit on the Root row after the first upgrade.
    with engine.begin() as conn:
        conn.execute(text(
            'UPDATE tenant_system_model_config SET value = :v '
            'WHERE tenant_id = 1 AND "key" = :k'
        ), {'v': '{"v": "EDITED"}', 'k': 'knowledge_llm'})

    # Re-run — the existing row must NOT be overwritten back to ROOT.
    _run_upgrade(engine)

    with engine.connect() as conn:
        value = conn.execute(text(
            'SELECT value FROM tenant_system_model_config '
            'WHERE tenant_id = 1 AND "key" = :k'
        ), {'k': 'knowledge_llm'}).scalar()
    assert value == '{"v": "EDITED"}'


# --- 4) downgrade ------------------------------------------------------------


def test_downgrade_drops_only_new_table_and_preserves_legacy_config(engine: Engine):
    """AD-06: downgrade rolls back the new table only. Legacy ``config``
    rows are kept as the rollback anchor."""
    with engine.begin() as conn:
        _create_legacy_config_table(conn)
        _seed_config_rows(conn, [(k, '{"v": 1}') for k in _FIVE_KEYS])

    _run_upgrade(engine)
    assert _table_exists(engine, 'tenant_system_model_config')

    _run_downgrade(engine)
    assert not _table_exists(engine, 'tenant_system_model_config')
    # Legacy rows preserved.
    assert _row_count(engine, 'config') == 5


def test_full_cycle_upgrade_downgrade_upgrade_remains_idempotent(engine: Engine):
    """downgrade → upgrade re-creates the table and re-applies backfill
    without errors or duplicate rows. Validates the full rollback &
    redeploy story (e.g. an aborted release).
    """
    with engine.begin() as conn:
        _create_legacy_config_table(conn)
        _seed_config_rows(conn, [(k, '{"v": 1}') for k in _FIVE_KEYS])

    _run_upgrade(engine)
    _run_downgrade(engine)
    _run_upgrade(engine)

    assert _row_count(engine, 'tenant_system_model_config') == 5


# --- 5) SQLModel.create_all preempted the table -----------------------------


def test_upgrade_skips_create_when_table_already_exists(engine: Engine):
    """Fresh-install path: app startup runs ``SQLModel.metadata.create_all()``
    *before* alembic. F034 must detect the pre-existing table and skip
    create_table — only the backfill should run."""
    # Pre-create the new table (simulating SQLModel.metadata.create_all).
    with engine.begin() as conn:
        conn.execute(text(
            """
            CREATE TABLE tenant_system_model_config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL,
                "key" VARCHAR(64) NOT NULL,
                value TEXT,
                is_shared_to_children SMALLINT,
                create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                update_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (tenant_id, "key")
            )
            """
        ))
        _create_legacy_config_table(conn)
        _seed_config_rows(conn, [(k, '{"v": 1}') for k in _FIVE_KEYS])

    # Must not raise even though create_table is essentially a no-op now.
    _run_upgrade(engine)

    # Backfill still runs — 5 rows present.
    assert _row_count(engine, 'tenant_system_model_config') == 5
