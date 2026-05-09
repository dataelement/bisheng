"""F023: preserve original SCM role for department-admin overlay sync.

Revision ID: f023_department_admin_membership_overlay
Revises: f022_approval_request
Create Date: 2026-04-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import column_exists

revision: str = 'f023_department_admin_membership_overlay'
down_revision: Union[str, Sequence[str], None] = 'f022_approval_request'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    conn = op.get_bind()
    if not column_exists(conn, 'space_channel_member', 'department_admin_promoted_from_role'):
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
    conn = op.get_bind()
    if column_exists(conn, 'space_channel_member', 'department_admin_promoted_from_role'):
        op.drop_column('space_channel_member', 'department_admin_promoted_from_role')
