"""F023: preserve original SCM role for department-admin overlay sync.

Revision ID: f023_department_admin_membership_overlay
Revises: f022_approval_request
Create Date: 2026-04-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f023_department_admin_membership_overlay'
down_revision: Union[str, Sequence[str], None] = 'f022_approval_request'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table_name: str, column_name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(sa.text(
        'SELECT COUNT(*) FROM information_schema.COLUMNS '
        'WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t AND COLUMN_NAME = :c'
    ), {'t': table_name, 'c': column_name})
    return result.scalar() > 0


def upgrade() -> None:
    if not _column_exists('space_channel_member', 'department_admin_promoted_from_role'):
        op.add_column(
            'space_channel_member',
            sa.Column(
                'department_admin_promoted_from_role',
                sa.String(length=32),
                nullable=True,
                comment='Original role before department-admin sync temporarily promoted the member',
            ),
        )


def downgrade() -> None:
    if _column_exists('space_channel_member', 'department_admin_promoted_from_role'):
        op.drop_column('space_channel_member', 'department_admin_promoted_from_role')
