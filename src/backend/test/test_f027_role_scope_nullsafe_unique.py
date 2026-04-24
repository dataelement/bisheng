"""Unit tests for F027 Alembic migration.

The migration turns role-name uniqueness into a NULL-safe constraint by
normalizing ``department_id IS NULL`` to a generated scope key column.
These tests patch alembic ``op.*`` calls instead of touching a real DB.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

MIGRATION_MOD = 'bisheng.core.database.alembic.versions.v2_5_1_f027_role_scope_nullsafe_unique'


def _build_conn(*, column_exists, constraint_exists, duplicate_rows):
    def _execute(stmt, params=None):
        sql = str(stmt)
        result = MagicMock()
        if 'information_schema.COLUMNS' in sql:
            name = (params or {}).get('c')
            result.scalar = MagicMock(return_value=1 if column_exists.get(name) else 0)
        elif 'information_schema.TABLE_CONSTRAINTS' in sql:
            name = (params or {}).get('c')
            result.scalar = MagicMock(return_value=1 if constraint_exists.get(name) else 0)
        elif 'GROUP BY tenant_id, role_type, role_name, COALESCE(department_id, -1)' in sql:
            result.fetchall = MagicMock(return_value=duplicate_rows)
        else:
            result.scalar = MagicMock(return_value=0)
            result.fetchall = MagicMock(return_value=[])
        return result

    conn = MagicMock()
    conn.execute = _execute
    return conn


def test_upgrade_adds_scope_key_and_swaps_to_nullsafe_unique_constraint():
    import importlib

    mig = importlib.import_module(MIGRATION_MOD)
    conn = _build_conn(
        column_exists={'department_scope_key': False},
        constraint_exists={
            'uk_tenant_roletype_rolename_scope': True,
            'uk_tenant_roletype_rolename_scope_key': False,
        },
        duplicate_rows=[],
    )

    with patch.object(mig.op, 'get_bind', return_value=conn), \
            patch.object(mig.op, 'add_column') as add_column, \
            patch.object(mig.op, 'drop_constraint') as drop_constraint, \
            patch.object(mig.op, 'create_unique_constraint') as create_unique_constraint, \
            patch.object(mig.op, 'execute') as op_execute:
        mig.upgrade()

    add_column.assert_called_once()
    assert add_column.call_args.args[0] == 'role'
    assert add_column.call_args.args[1].name == 'department_scope_key'
    drop_constraint.assert_called_once_with(
        'uk_tenant_roletype_rolename_scope',
        'role',
        type_='unique',
    )
    create_unique_constraint.assert_called_once_with(
        'uk_tenant_roletype_rolename_scope_key',
        'role',
        ['tenant_id', 'role_type', 'role_name', 'department_scope_key'],
    )
    op_execute.assert_not_called()


def test_upgrade_dedupes_existing_null_scope_collisions_before_creating_constraint():
    import importlib

    mig = importlib.import_module(MIGRATION_MOD)
    conn = _build_conn(
        column_exists={'department_scope_key': True},
        constraint_exists={
            'uk_tenant_roletype_rolename_scope': True,
            'uk_tenant_roletype_rolename_scope_key': False,
        },
        duplicate_rows=[
            SimpleNamespace(
                tenant_id=1,
                role_type='tenant',
                role_name='Ops',
                scope_key=-1,
                cnt=2,
            ),
        ],
    )

    with patch.object(mig.op, 'get_bind', return_value=conn), \
            patch.object(mig.op, 'add_column') as add_column, \
            patch.object(mig.op, 'drop_constraint'), \
            patch.object(mig.op, 'create_unique_constraint') as create_unique_constraint, \
            patch.object(mig.op, 'execute') as op_execute:
        mig.upgrade()

    add_column.assert_not_called()
    op_execute.assert_called_once()
    assert 'ROW_NUMBER() OVER' in op_execute.call_args.args[0]
    assert 'COALESCE(department_id, -1)' in op_execute.call_args.args[0]
    create_unique_constraint.assert_called_once()


def test_downgrade_restores_previous_constraint_and_drops_scope_key():
    import importlib

    mig = importlib.import_module(MIGRATION_MOD)
    conn = _build_conn(
        column_exists={'department_scope_key': True},
        constraint_exists={
            'uk_tenant_roletype_rolename_scope': False,
            'uk_tenant_roletype_rolename_scope_key': True,
        },
        duplicate_rows=[],
    )

    with patch.object(mig.op, 'get_bind', return_value=conn), \
            patch.object(mig.op, 'drop_constraint') as drop_constraint, \
            patch.object(mig.op, 'create_unique_constraint') as create_unique_constraint, \
            patch.object(mig.op, 'drop_column') as drop_column:
        mig.downgrade()

    drop_constraint.assert_called_once_with(
        'uk_tenant_roletype_rolename_scope_key',
        'role',
        type_='unique',
    )
    create_unique_constraint.assert_called_once_with(
        'uk_tenant_roletype_rolename_scope',
        'role',
        ['tenant_id', 'role_type', 'role_name', 'department_id'],
    )
    drop_column.assert_called_once_with('role', 'department_scope_key')
