"""F024: add ``role.create_user`` and backfill from role audit logs.

Revision ID: f024_role_creator
Revises: f023_department_admin_membership_overlay
Create Date: 2026-04-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f024_role_creator'
down_revision: Union[str, Sequence[str], None] = 'f023_department_admin_membership_overlay'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(sa.text(
        'SELECT COUNT(*) FROM information_schema.TABLES '
        'WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t'
    ), {'t': table_name})
    return result.scalar() > 0


def _column_exists(table_name: str, column_name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(sa.text(
        'SELECT COUNT(*) FROM information_schema.COLUMNS '
        'WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t AND COLUMN_NAME = :c'
    ), {'t': table_name, 'c': column_name})
    return result.scalar() > 0


def _backfill_role_creator_from_auditlog() -> None:
    conn = op.get_bind()
    conn.execute(sa.text(
        'UPDATE role r '
        'JOIN ('
        '  SELECT '
        '    CAST(t.object_id AS UNSIGNED) AS role_id, '
        '    t.operator_id AS creator_id '
        '  FROM ('
        '    SELECT '
        '      object_id, '
        '      operator_id, '
        '      ROW_NUMBER() OVER (PARTITION BY object_id ORDER BY create_time ASC, id ASC) AS rn '
        '    FROM auditlog '
        "    WHERE system_id = 'system' "
        "      AND event_type = 'create_role' "
        "      AND object_type = 'role_conf' "
        "      AND object_id REGEXP '^[0-9]+$' "
        '  ) t '
        '  WHERE t.rn = 1'
        ') s ON s.role_id = r.id '
        'SET r.create_user = s.creator_id '
        'WHERE r.create_user IS NULL'
    ))


def upgrade() -> None:
    if not _column_exists('role', 'create_user'):
        op.add_column(
            'role',
            sa.Column('create_user', sa.Integer(), nullable=True, comment='Role creator user ID'),
        )

    if _table_exists('auditlog') and _column_exists('role', 'create_user'):
        _backfill_role_creator_from_auditlog()


def downgrade() -> None:
    if _column_exists('role', 'create_user'):
        op.drop_column('role', 'create_user')
