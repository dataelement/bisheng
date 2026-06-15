"""F020 Alembic migration unit tests (v2_5_1_f020_llm_tenant).

These don't touch a real DB — alembic ``op.*`` calls are patched and the
bound connection's ``execute`` returns canned results. The goal is to
cover the two decision paths of ``upgrade()``:

1. Pre-check finds ``(tenant_id, name)`` duplicates → abort with a
   RuntimeError whose message lists the conflicts (T04 AC-16 edge case,
   spec §5.5 STEP1).
2. No conflicts + old index present → drop old, create composite unique
   (T04 AC-16 happy path).

Running under ``pytest`` with the project venv; no external fixtures.
"""

from unittest.mock import MagicMock, patch

import pytest

MIGRATION_MOD = 'bisheng.core.database.alembic.versions.v2_5_1_f020_llm_tenant'


def _build_conn(duplicate_rows, index_exists):
    """Build a connection whose ``execute`` dispatches based on the SQL.

    Parameters
    ----------
    duplicate_rows : list
        Rows returned by the GROUP BY pre-check (empty = no conflicts).
    index_exists : dict[str, bool]
        Maps ``INDEX_NAME`` bind param to the existence answer.
    """

    def _execute(stmt, params=None):
        sql = str(stmt)
        result = MagicMock()
        if 'GROUP BY' in sql:
            result.fetchall = MagicMock(return_value=duplicate_rows)
        elif 'STATISTICS' in sql:
            idx_name = (params or {}).get('i')
            result.scalar = MagicMock(
                return_value=1 if index_exists.get(idx_name) else 0
            )
        else:
            result.scalar = MagicMock(return_value=0)
        return result

    conn = MagicMock()
    conn.execute = _execute
    return conn


def test_upgrade_rejects_duplicate_tenant_name_pairs():
    """Pre-check finds duplicates → RuntimeError mentions them and aborts."""
    import importlib
    mig = importlib.import_module(MIGRATION_MOD)

    row = MagicMock()
    row.tenant_id = 5
    row.name = 'Azure-GPT-4'
    row.cnt = 2
    conn = _build_conn(duplicate_rows=[row], index_exists={})

    with patch.object(mig.op, 'get_bind', return_value=conn), \
            patch.object(mig.op, 'drop_index') as drop, \
            patch.object(mig.op, 'create_index') as create:
        with pytest.raises(RuntimeError) as excinfo:
            mig.upgrade()

    msg = str(excinfo.value)
    assert 'duplicate' in msg.lower() or 'duplicate' in msg
    assert 'tenant_id=5' in msg
    assert 'Azure-GPT-4' in msg
    # No DDL should have been issued on the failure path.
    drop.assert_not_called()
    create.assert_not_called()


def test_upgrade_creates_composite_unique_index():
    """No conflicts + old UNIQUE(name) exists → swap to composite index."""
    import importlib
    mig = importlib.import_module(MIGRATION_MOD)

    conn = _build_conn(
        duplicate_rows=[],
        index_exists={
            'name': True,                         # legacy UNIQUE(name)
            'uk_llm_server_tenant_name': False,   # composite not yet present
        },
    )

    with patch.object(mig.op, 'get_bind', return_value=conn), \
            patch.object(mig.op, 'drop_index') as drop, \
            patch.object(mig.op, 'create_index') as create:
        mig.upgrade()

    drop.assert_called_once_with('name', table_name='llm_server')
    create.assert_called_once_with(
        'uk_llm_server_tenant_name',
        'llm_server',
        ['tenant_id', 'name'],
        unique=True,
    )


def test_upgrade_skips_drop_when_legacy_index_absent():
    """Fresh v2.5.1 install (no legacy UNIQUE(name)) → just create composite."""
    import importlib
    mig = importlib.import_module(MIGRATION_MOD)

    conn = _build_conn(
        duplicate_rows=[],
        index_exists={'name': False, 'uk_llm_server_tenant_name': False},
    )

    with patch.object(mig.op, 'get_bind', return_value=conn), \
            patch.object(mig.op, 'drop_index') as drop, \
            patch.object(mig.op, 'create_index') as create:
        mig.upgrade()

    drop.assert_not_called()
    create.assert_called_once_with(
        'uk_llm_server_tenant_name',
        'llm_server',
        ['tenant_id', 'name'],
        unique=True,
    )
