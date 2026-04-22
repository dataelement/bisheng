"""F024: add per-space approval settings to department knowledge spaces.

Revision ID: f024_department_space_per_space_approval_settings
Revises: f023_department_admin_membership_overlay
Create Date: 2026-04-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f024_department_space_per_space_approval_settings'
down_revision: Union[str, Sequence[str], None] = 'f023_department_admin_membership_overlay'
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
    if not _column_exists('department_knowledge_space', 'approval_enabled'):
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
    if not _column_exists('department_knowledge_space', 'sensitive_check_enabled'):
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
    if _column_exists('department_knowledge_space', 'sensitive_check_enabled'):
        op.drop_column('department_knowledge_space', 'sensitive_check_enabled')
    if _column_exists('department_knowledge_space', 'approval_enabled'):
        op.drop_column('department_knowledge_space', 'approval_enabled')
