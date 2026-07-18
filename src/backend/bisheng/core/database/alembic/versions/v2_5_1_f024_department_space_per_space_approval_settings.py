"""F024: add per-space approval settings to department knowledge spaces.

Revision ID: f024_department_space_per_space_approval_settings
Revises: f023_department_admin_membership_overlay
Create Date: 2026-04-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import column_exists

revision: str = 'f024_department_space_per_space_approval_settings'
down_revision: Union[str, Sequence[str], None] = 'f023_department_admin_membership_overlay'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    conn = op.get_bind()
    if not column_exists(conn, 'department_knowledge_space', 'approval_enabled'):
        op.add_column(
            'department_knowledge_space',
            sa.Column(
                'approval_enabled',
                sa.Boolean(),
                nullable=False,
                server_default=sa.text('1'),
                comment='Whether uploads in this department knowledge space require approval',
            ),
        )
    if not column_exists(conn, 'department_knowledge_space', 'sensitive_check_enabled'):
        op.add_column(
            'department_knowledge_space',
            sa.Column(
                'sensitive_check_enabled',
                sa.Boolean(),
                nullable=False,
                server_default=sa.text('0'),
                comment='Whether uploads in this department knowledge space require content safety check',
            ),
        )

def downgrade() -> None:
    conn = op.get_bind()
    if column_exists(conn, 'department_knowledge_space', 'sensitive_check_enabled'):
        op.drop_column('department_knowledge_space', 'sensitive_check_enabled')
    if column_exists(conn, 'department_knowledge_space', 'approval_enabled'):
        op.drop_column('department_knowledge_space', 'approval_enabled')
