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

from bisheng.core.database.dialect_helpers import column_exists, constraint_exists

revision: str = 'f027_role_scope_nullsafe_unique'
down_revision: Union[str, Sequence[str], None] = 'f026_role_scope_name_unique'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    if not column_exists(conn, 'role', 'department_scope_key'):
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

    if constraint_exists(conn, 'role', 'uk_tenant_roletype_rolename_scope'):
        op.drop_constraint('uk_tenant_roletype_rolename_scope', 'role', type_='unique')

    if not constraint_exists(conn, 'role', 'uk_tenant_roletype_rolename_scope_key'):
        # Detect and rename duplicate (tenant_id, role_type, role_name, scope_key) rows
        # before creating the unique constraint. Uses SQLAlchemy expression language
        # so the GROUP BY + per-row UPDATE works on MySQL and DaMeng alike.
        role_tbl = sa.Table('role', sa.MetaData(), autoload_with=conn)
        scope_key_expr = sa.func.coalesce(role_tbl.c.department_id, -1)

        conflicts = conn.execute(
            sa.select(
                role_tbl.c.tenant_id,
                role_tbl.c.role_type,
                role_tbl.c.role_name,
                scope_key_expr.label('scope_key'),
                sa.func.count().label('cnt'),
            )
            .group_by(
                role_tbl.c.tenant_id,
                role_tbl.c.role_type,
                role_tbl.c.role_name,
                scope_key_expr,
            )
            .having(sa.func.count() > 1)
        ).fetchall()

        for row in conflicts:
            print(
                f'[f027] dedupe role scope collision: tenant_id={row.tenant_id} '
                f'role_type={row.role_type!r} role_name={row.role_name!r} '
                f'scope_key={row.scope_key} count={row.cnt}'
            )
            # Fetch all duplicate IDs for this group, ordered (first kept, rest renamed)
            dup_ids = conn.execute(
                sa.select(role_tbl.c.id)
                .where(
                    role_tbl.c.tenant_id == row.tenant_id,
                    role_tbl.c.role_type == row.role_type,
                    role_tbl.c.role_name == row.role_name,
                    scope_key_expr == row.scope_key,
                )
                .order_by(role_tbl.c.id)
            ).fetchall()

            for (row_id,) in dup_ids[1:]:
                conn.execute(
                    sa.update(role_tbl)
                    .where(role_tbl.c.id == row_id)
                    .values(role_name=sa.func.concat(
                        role_tbl.c.role_name, sa.literal(f'-dup-{row_id}')
                    ))
                )

        op.create_unique_constraint(
            'uk_tenant_roletype_rolename_scope_key',
            'role',
            ['tenant_id', 'role_type', 'role_name', 'department_scope_key'],
        )


def downgrade() -> None:
    conn = op.get_bind()
    if constraint_exists(conn, 'role', 'uk_tenant_roletype_rolename_scope_key'):
        op.drop_constraint('uk_tenant_roletype_rolename_scope_key', 'role', type_='unique')

    if not constraint_exists(conn, 'role', 'uk_tenant_roletype_rolename_scope'):
        op.create_unique_constraint(
            'uk_tenant_roletype_rolename_scope',
            'role',
            ['tenant_id', 'role_type', 'role_name', 'department_id'],
        )

    if column_exists(conn, 'role', 'department_scope_key'):
        op.drop_column('role', 'department_scope_key')
