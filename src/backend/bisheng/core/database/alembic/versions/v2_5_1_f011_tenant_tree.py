"""F011: Tenant tree model — v2.5.1 first migration.

Revision ID: f011_tenant_tree
Revises: f011_backfill_create_knowledge_web_menu
Create Date: 2026-04-19

Changes:
  - ALTER tenant: add parent_tenant_id (+ index), share_default_to_children.
  - ALTER user_tenant: add is_active, backfill it from (status='active' AND
    is_default=1), dedup multi-active rows, replace uk_user_tenant with
    uk_user_active(user_id, is_active).
  - ALTER department: add is_tenant_root, mounted_tenant_id (+ index).
  - ALTER auditlog: add tenant_id (+ index), operator_tenant_id, action
    (+ index), target_type, target_id, reason, metadata.
  - Backfill Root tenant shape (parent_tenant_id=NULL, share_default=1).

Non-DDL logic lives in ``bisheng.core.database.alembic_helpers.f011`` so
it can be unit-tested independently (see ``test/test_f011_migration.py``).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.f011 import (
    backfill_is_active,
    deduplicate_multi_active_user_tenants,
    ensure_root_tenant_shape,
)

from bisheng.core.database.dialect_helpers import column_exists, index_exists

revision: str = 'f011_tenant_tree'
down_revision: Union[str, Sequence[str], None] = 'f011_backfill_create_knowledge_web_menu'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    conn = op.get_bind()
    # -------------------------------------------------------------------
    # 1. tenant: add parent_tenant_id + share_default_to_children.
    # -------------------------------------------------------------------
    if not column_exists(conn, 'tenant', 'parent_tenant_id'):
        op.add_column(
            'tenant',
            sa.Column('parent_tenant_id', sa.Integer, nullable=True,
                      comment='NULL=Root; else Root id (MVP 2-layer lock)'),
        )
    if not index_exists(conn, 'tenant', 'idx_tenant_parent'):
        op.create_index('idx_tenant_parent', 'tenant', ['parent_tenant_id'])
    if not column_exists(conn, 'tenant', 'share_default_to_children'):
        op.add_column(
            'tenant',
            sa.Column('share_default_to_children', sa.Integer, nullable=False,
                      server_default='1',
                      comment='1=Root resources default-shared to children'),
        )

    # 2. Root tenant backfill (uses helper).
    ensure_root_tenant_shape(op.get_bind())

    # -------------------------------------------------------------------
    # 3. user_tenant: add is_active, backfill, dedup, swap unique index.
    # -------------------------------------------------------------------
    if not column_exists(conn, 'user_tenant', 'is_active'):
        op.add_column(
            'user_tenant',
            sa.Column('is_active', sa.Integer, nullable=True,
                      comment='1=active leaf (unique per user); NULL=history'),
        )
    backfill_is_active(op.get_bind())
    deduplicate_multi_active_user_tenants(op.get_bind())
    if index_exists(conn, 'user_tenant', 'uk_user_tenant'):
        op.drop_constraint('uk_user_tenant', 'user_tenant', type_='unique')
    if not index_exists(conn, 'user_tenant', 'uk_user_active'):
        op.create_unique_constraint(
            'uk_user_active', 'user_tenant', ['user_id', 'is_active'],
        )

    # -------------------------------------------------------------------
    # 4. department: add is_tenant_root, mounted_tenant_id.
    # -------------------------------------------------------------------
    if not column_exists(conn, 'department', 'is_tenant_root'):
        op.add_column(
            'department',
            sa.Column('is_tenant_root', sa.Integer, nullable=False,
                      server_default='0',
                      comment='1=Tenant mount point (Child Tenant root dept)'),
        )
    if not column_exists(conn, 'department', 'mounted_tenant_id'):
        op.add_column(
            'department',
            sa.Column('mounted_tenant_id', sa.Integer, nullable=True,
                      comment='FK→tenant.id when is_tenant_root=1'),
        )
    if not index_exists(conn, 'department', 'idx_dept_mounted_tenant'):
        op.create_index(
            'idx_dept_mounted_tenant', 'department', ['mounted_tenant_id'],
        )

    # -------------------------------------------------------------------
    # 5. auditlog: append structured v2 columns (tenant_id already added
    #    by F001 TENANT_TABLES; only extend with the new ones here).
    # -------------------------------------------------------------------
    if not column_exists(conn, 'auditlog', 'operator_tenant_id'):
        op.add_column(
            'auditlog',
            sa.Column('operator_tenant_id', sa.Integer, nullable=True,
                      comment='v2.5.1: operator leaf tenant'),
        )
    if not column_exists(conn, 'auditlog', 'action'):
        op.add_column(
            'auditlog',
            sa.Column('action', sa.String(64), nullable=True,
                      comment='v2.5.1: structured action name (see spec §5.4.2)'),
        )
    if not index_exists(conn, 'auditlog', 'idx_auditlog_action'):
        op.create_index('idx_auditlog_action', 'auditlog', ['action'])
    if not column_exists(conn, 'auditlog', 'target_type'):
        op.add_column(
            'auditlog',
            sa.Column('target_type', sa.String(32), nullable=True),
        )
    if not column_exists(conn, 'auditlog', 'target_id'):
        op.add_column(
            'auditlog',
            sa.Column('target_id', sa.String(64), nullable=True),
        )
    if not column_exists(conn, 'auditlog', 'reason'):
        op.add_column(
            'auditlog',
            sa.Column('reason', sa.Text, nullable=True),
        )
    if not column_exists(conn, 'auditlog', 'metadata'):
        op.add_column(
            'auditlog',
            sa.Column('metadata', sa.JSON, nullable=True,
                      comment='v2.5.1: extended fields'),
        )
    if not index_exists(conn, 'auditlog', 'idx_auditlog_tenant_time'):
        # tenant_id already exists (F001 TENANT_TABLES); just add compound index.
        op.create_index(
            'idx_auditlog_tenant_time', 'auditlog', ['tenant_id', 'create_time'],
        )

def downgrade() -> None:
    conn = op.get_bind()
    # auditlog — reverse order of upgrade.
    if index_exists(conn, 'auditlog', 'idx_auditlog_tenant_time'):
        op.drop_index('idx_auditlog_tenant_time', table_name='auditlog')
    for col in ('metadata', 'reason', 'target_id', 'target_type'):
        if column_exists(conn, 'auditlog', col):
            op.drop_column('auditlog', col)
    if index_exists(conn, 'auditlog', 'idx_auditlog_action'):
        op.drop_index('idx_auditlog_action', table_name='auditlog')
    if column_exists(conn, 'auditlog', 'action'):
        op.drop_column('auditlog', 'action')
    if column_exists(conn, 'auditlog', 'operator_tenant_id'):
        op.drop_column('auditlog', 'operator_tenant_id')

    # department.
    if index_exists(conn, 'department', 'idx_dept_mounted_tenant'):
        op.drop_index('idx_dept_mounted_tenant', table_name='department')
    if column_exists(conn, 'department', 'mounted_tenant_id'):
        op.drop_column('department', 'mounted_tenant_id')
    if column_exists(conn, 'department', 'is_tenant_root'):
        op.drop_column('department', 'is_tenant_root')

    # user_tenant — cannot recover is_active → original split; restore
    # uk_user_tenant and drop the new column + constraint.
    if index_exists(conn, 'user_tenant', 'uk_user_active'):
        op.drop_constraint('uk_user_active', 'user_tenant', type_='unique')
    if not index_exists(conn, 'user_tenant', 'uk_user_tenant'):
        op.create_unique_constraint(
            'uk_user_tenant', 'user_tenant', ['user_id', 'tenant_id'],
        )
    if column_exists(conn, 'user_tenant', 'is_active'):
        op.drop_column('user_tenant', 'is_active')

    # tenant.
    if column_exists(conn, 'tenant', 'share_default_to_children'):
        op.drop_column('tenant', 'share_default_to_children')
    if index_exists(conn, 'tenant', 'idx_tenant_parent'):
        op.drop_index('idx_tenant_parent', table_name='tenant')
    if column_exists(conn, 'tenant', 'parent_tenant_id'):
        op.drop_column('tenant', 'parent_tenant_id')
