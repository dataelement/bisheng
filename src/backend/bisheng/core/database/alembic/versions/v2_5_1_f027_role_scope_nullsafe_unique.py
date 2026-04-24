"""F027: make role scope uniqueness NULL-safe.

Revision ID: f027_role_scope_nullsafe_unique
Revises: f026_role_scope_name_unique
Create Date: 2026-04-23

Changes:
  - ADD COLUMN department_scope_key INT GENERATED ALWAYS AS (COALESCE(department_id, -1)) STORED
  - DROP UNIQUE uk_tenant_roletype_rolename_scope
  - CREATE UNIQUE uk_tenant_roletype_rolename_scope_key
    ON role(tenant_id, role_type, role_name, department_scope_key)

Why:
  - MySQL UNIQUE allows multiple NULL values.
  - The previous F026 constraint fixed cross-department duplicates, but still
    could not enforce uniqueness for global-scope roles where
    ``department_id IS NULL``.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f027_role_scope_nullsafe_unique'
down_revision: Union[str, Sequence[str], None] = 'f026_role_scope_name_unique'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table_name: str, column_name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT COUNT(*) FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t AND COLUMN_NAME = :c"
    ), {'t': table_name, 'c': column_name})
    return result.scalar() > 0


def _constraint_exists(table_name: str, constraint_name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t AND CONSTRAINT_NAME = :c"
    ), {'t': table_name, 'c': constraint_name})
    return result.scalar() > 0


def upgrade() -> None:
    if not _column_exists('role', 'department_scope_key'):
        op.add_column(
            'role',
            sa.Column(
                'department_scope_key',
                sa.Integer(),
                sa.Computed('COALESCE(department_id, -1)', persisted=True),
                nullable=False,
                comment='Normalized department scope key; -1 = no scope restriction',
            ),
        )

    if _constraint_exists('role', 'uk_tenant_roletype_rolename_scope'):
        op.drop_constraint('uk_tenant_roletype_rolename_scope', 'role', type_='unique')

    if not _constraint_exists('role', 'uk_tenant_roletype_rolename_scope_key'):
        conn = op.get_bind()
        conflicts = conn.execute(sa.text("""
            SELECT tenant_id,
                   role_type,
                   role_name,
                   COALESCE(department_id, -1) AS scope_key,
                   COUNT(*) AS cnt
            FROM role
            GROUP BY tenant_id, role_type, role_name, COALESCE(department_id, -1)
            HAVING cnt > 1
        """)).fetchall()

        for row in conflicts:
            tenant_id = row[0] if isinstance(row, (list, tuple)) else getattr(row, 'tenant_id')
            role_type = row[1] if isinstance(row, (list, tuple)) else getattr(row, 'role_type')
            role_name = row[2] if isinstance(row, (list, tuple)) else getattr(row, 'role_name')
            scope_key = row[3] if isinstance(row, (list, tuple)) else getattr(row, 'scope_key')
            count = row[4] if isinstance(row, (list, tuple)) else getattr(row, 'cnt')
            print(
                f'[f027] dedupe role scope collision: tenant_id={tenant_id} '
                f'role_type={role_type!r} role_name={role_name!r} scope_key={scope_key} count={count}'
            )

        if conflicts:
            op.execute("""
                UPDATE role AS r
                JOIN (
                    SELECT id,
                           ROW_NUMBER() OVER (
                               PARTITION BY tenant_id, role_type, role_name, COALESCE(department_id, -1)
                               ORDER BY id
                           ) AS rn
                    FROM role
                ) AS t ON r.id = t.id
                SET r.role_name = CONCAT(r.role_name, '-dup-', r.id)
                WHERE t.rn > 1
            """)

        op.create_unique_constraint(
            'uk_tenant_roletype_rolename_scope_key',
            'role',
            ['tenant_id', 'role_type', 'role_name', 'department_scope_key'],
        )


def downgrade() -> None:
    if _constraint_exists('role', 'uk_tenant_roletype_rolename_scope_key'):
        op.drop_constraint('uk_tenant_roletype_rolename_scope_key', 'role', type_='unique')

    if not _constraint_exists('role', 'uk_tenant_roletype_rolename_scope'):
        op.create_unique_constraint(
            'uk_tenant_roletype_rolename_scope',
            'role',
            ['tenant_id', 'role_type', 'role_name', 'department_id'],
        )

    if _column_exists('role', 'department_scope_key'):
        op.drop_column('role', 'department_scope_key')
