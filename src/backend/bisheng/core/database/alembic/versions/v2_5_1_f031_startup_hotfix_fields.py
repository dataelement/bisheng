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


revision: str = 'f031_startup_hotfix_fields'
down_revision: Union[str, Sequence[str], None] = 'f030_tenant_root_dept_id_backfill'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table_name: str, column_name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            'SELECT COUNT(*) FROM information_schema.COLUMNS '
            'WHERE TABLE_SCHEMA = DATABASE() '
            '  AND TABLE_NAME = :t AND COLUMN_NAME = :c'
        ),
        {'t': table_name, 'c': column_name},
    )
    return result.scalar() > 0


def _index_exists(table_name: str, index_name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            'SELECT COUNT(*) FROM information_schema.STATISTICS '
            'WHERE TABLE_SCHEMA = DATABASE() '
            '  AND TABLE_NAME = :t AND INDEX_NAME = :i'
        ),
        {'t': table_name, 'i': index_name},
    )
    return result.scalar() > 0


def upgrade() -> None:
    if not _column_exists('department', 'concurrent_session_limit'):
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

    if not _column_exists('user', 'disable_source'):
        op.add_column(
            'user',
            sa.Column(
                'disable_source',
                sa.String(length=32),
                nullable=True,
                comment='Set when delete=1 was forced by org sync/SSO; blocks non-super re-enable',
            ),
        )
    if not _index_exists('user', 'ix_user_disable_source'):
        op.create_index('ix_user_disable_source', 'user', ['disable_source'])


def downgrade() -> None:
    if _index_exists('user', 'ix_user_disable_source'):
        op.drop_index('ix_user_disable_source', table_name='user')
    if _column_exists('user', 'disable_source'):
        op.drop_column('user', 'disable_source')
    if _column_exists('department', 'concurrent_session_limit'):
        op.drop_column('department', 'concurrent_session_limit')

