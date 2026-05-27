"""F005: Extend role table with role_type, department_id, quota_config.

Revision ID: f005_role_menu_quota
Revises: f004_rebac
Create Date: 2026-04-12

Changes:
  - ADD COLUMN role_type VARCHAR(16) NOT NULL DEFAULT 'tenant'
  - ADD COLUMN department_id INT NULL (indexed)
  - ADD COLUMN quota_config JSON NULL
  - DROP INDEX group_role_name_uniq
  - Pre-dedupe legacy (tenant_id, role_type, role_name) collisions before
    building the new unique index (rename non-oldest rows to
    ``<role_name>-dup-<id>``); keeps pre-v2.5 installations migrateable
    when historical data contains same-named roles.
  - CREATE UNIQUE INDEX uk_tenant_roletype_rolename ON role(tenant_id, role_type, role_name)
  - Backfill: AdminRole(1) and DefaultRole(2) set role_type='global'
  - Migrate: knowledge_space_file_limit > 0 values into quota_config
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import JsonType, column_exists, index_exists

revision: str = 'f005_role_menu_quota'
down_revision: Union[str, Sequence[str], None] = 'f004_rebac'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    """Extend role table for policy-role model (F005)."""
    conn = op.get_bind()

    # 1. Add role_type column
    if not column_exists(conn, 'role', 'role_type'):
        op.add_column(
            'role',
            sa.Column('role_type', sa.String(16), nullable=False, server_default='tenant',
                      comment='global: cross-tenant visible; tenant: tenant-scoped'),
        )

    # 2. Add department_id column with index
    if not column_exists(conn, 'role', 'department_id'):
        op.add_column(
            'role',
            sa.Column('department_id', sa.Integer, nullable=True,
                      comment='Department scope ID; NULL = no scope restriction'),
        )
    if not index_exists(conn, 'role', 'idx_role_department_id'):
        op.create_index('idx_role_department_id', 'role', ['department_id'])

    # 3. Add quota_config JSON column
    if not column_exists(conn, 'role', 'quota_config'):
        op.add_column(
            'role',
            sa.Column('quota_config', JsonType, nullable=True,
                      comment='Resource quota config JSON'),
        )

    # 4. Drop old unique constraint and create new one
    if index_exists(conn, 'role', 'group_role_name_uniq'):
        op.drop_index('group_role_name_uniq', table_name='role')

    # 4a. Pre-dedupe legacy collisions so the new UNIQUE can be built.
    # Keep the oldest row's role_name intact; rename the rest to
    # ``<role_name>-dup-<id>`` (id is globally unique, so the new names
    # will not collide with each other). Idempotent: runs only when the
    # target unique index is not yet present. SQLAlchemy expression language
    # is used so the dedupe works on MySQL and DM8 alike — MySQL multi-table
    # UPDATE...JOIN is not portable to DM8 (Oracle-compatible).
    if not index_exists(conn, 'role', 'uk_tenant_roletype_rolename'):
        role_tbl = sa.Table('role', sa.MetaData(), autoload_with=conn)
        conflicts = conn.execute(
            sa.select(
                role_tbl.c.tenant_id,
                role_tbl.c.role_type,
                role_tbl.c.role_name,
                sa.func.count().label('cnt'),
            )
            .group_by(role_tbl.c.tenant_id, role_tbl.c.role_type, role_tbl.c.role_name)
            .having(sa.func.count() > 1)
        ).fetchall()
        for row in conflicts:
            print(
                f'[f005] dedupe role_name collision: tenant_id={row.tenant_id} '
                f'role_type={row.role_type!r} role_name={row.role_name!r} count={row.cnt}'
            )
            # Keep the lowest id (oldest row) untouched, rename the rest.
            dup_ids = conn.execute(
                sa.select(role_tbl.c.id)
                .where(
                    role_tbl.c.tenant_id == row.tenant_id,
                    role_tbl.c.role_type == row.role_type,
                    role_tbl.c.role_name == row.role_name,
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
            'uk_tenant_roletype_rolename', 'role',
            ['tenant_id', 'role_type', 'role_name'],
        )

    # 5. Backfill: set built-in roles to global
    role_tbl = sa.Table('role', sa.MetaData(), autoload_with=conn)
    conn.execute(
        sa.update(role_tbl)
        .where(role_tbl.c.id.in_([1, 2]))
        .values(role_type='global')
    )

    # 6. Migrate knowledge_space_file_limit into quota_config
    # Only for roles that have a positive limit set.
    # Use Python-level JSON processing so the query works on MySQL and DaMeng.
    if column_exists(conn, 'role', 'knowledge_space_file_limit'):
        import json as _json
        role_tbl = sa.Table('role', sa.MetaData(), autoload_with=conn)
        rows = conn.execute(
            sa.select(role_tbl.c.id, role_tbl.c.knowledge_space_file_limit, role_tbl.c.quota_config)
            .where(role_tbl.c.knowledge_space_file_limit > 0)
        ).fetchall()
        for row in rows:
            raw = row.quota_config
            current = _json.loads(raw) if isinstance(raw, str) else raw
            if current:  # already has config — skip
                continue
            conn.execute(
                sa.update(role_tbl)
                .where(role_tbl.c.id == row.id)
                .values(quota_config=_json.dumps({'knowledge_space_file': row.knowledge_space_file_limit}))
            )

def downgrade() -> None:
    """Revert role table changes."""
    conn = op.get_bind()
    # Clear migrated quota_config values using Python-level JSON check
    import json as _json
    role_tbl = sa.Table('role', sa.MetaData(), autoload_with=conn)
    rows = conn.execute(
        sa.select(role_tbl.c.id, role_tbl.c.quota_config)
        .where(role_tbl.c.quota_config.isnot(None))
    ).fetchall()
    for row in rows:
        raw = row.quota_config
        current = _json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(current, dict) and list(current.keys()) == ['knowledge_space_file']:
            conn.execute(
                sa.update(role_tbl).where(role_tbl.c.id == row.id).values(quota_config=None)
            )

    # Revert built-in roles
    role_tbl = sa.Table('role', sa.MetaData(), autoload_with=conn)
    conn.execute(
        sa.update(role_tbl)
        .where(role_tbl.c.id.in_([1, 2]))
        .values(role_type='tenant')
    )

    # Drop new unique constraint and restore old one
    op.drop_constraint('uk_tenant_roletype_rolename', 'role', type_='unique')
    op.create_unique_constraint('group_role_name_uniq', 'role', ['group_id', 'role_name'])

    # Drop new columns
    op.drop_column('role', 'quota_config')
    op.drop_index('idx_role_department_id', table_name='role')
    op.drop_column('role', 'department_id')
    op.drop_column('role', 'role_type')
