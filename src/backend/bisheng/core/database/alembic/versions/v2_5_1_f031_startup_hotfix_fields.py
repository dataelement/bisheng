"""F031: add startup hotfix fields used by traffic and SSO sync.

Revision ID: f031_startup_hotfix_fields
Revises: f030_tenant_root_dept_id_backfill
Create Date: 2026-04-27

Why:
  The deployed backend imports models that already include
  ``department.concurrent_session_limit`` and ``user.disable_source``. Test
  environments that had not received those schema changes failed at startup or
  login with MySQL 1054 "Unknown column" errors.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import column_exists, index_exists

revision: str = 'f031_startup_hotfix_fields'
down_revision: Union[str, Sequence[str], None] = 'f030_tenant_root_dept_id_backfill'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    conn = op.get_bind()
    if not column_exists(conn, 'department', 'concurrent_session_limit'):
        op.add_column(
            'department',
            sa.Column(
                'concurrent_session_limit',
                sa.Integer,
                nullable=False,
                server_default='0',
                comment='Dept-wide max concurrent daily-mode chat users; 0=unlimited (F030)',
            ),
        )

    if not column_exists(conn, 'user', 'disable_source'):
        op.add_column(
            'user',
            sa.Column(
                'disable_source',
                sa.String(length=32),
                nullable=True,
                comment='Set when delete=1 was forced by org sync/SSO; blocks non-super re-enable',
            ),
        )
    if not index_exists(conn, 'user', 'ix_user_disable_source'):
        op.create_index('ix_user_disable_source', 'user', ['disable_source'])

def downgrade() -> None:
    conn = op.get_bind()
    if index_exists(conn, 'user', 'ix_user_disable_source'):
        op.drop_index('ix_user_disable_source', table_name='user')
    if column_exists(conn, 'user', 'disable_source'):
        op.drop_column('user', 'disable_source')
    if column_exists(conn, 'department', 'concurrent_session_limit'):
        op.drop_column('department', 'concurrent_session_limit')

