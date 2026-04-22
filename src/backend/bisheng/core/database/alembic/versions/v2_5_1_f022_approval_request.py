"""F022: add approval_request table for department knowledge space uploads.

Revision ID: f022_approval_request
Revises: f021_department_knowledge_space
Create Date: 2026-04-21
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f022_approval_request'
down_revision: Union[str, Sequence[str], None] = 'f021_department_knowledge_space'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(sa.text(
        'SELECT COUNT(*) FROM information_schema.TABLES '
        'WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t'
    ), {'t': name})
    return result.scalar() > 0


def _index_exists(table_name: str, index_name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(sa.text(
        'SELECT COUNT(*) FROM information_schema.STATISTICS '
        'WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t AND INDEX_NAME = :i'
    ), {'t': table_name, 'i': index_name})
    return result.scalar() > 0


def upgrade() -> None:
    if not _table_exists('approval_request'):
        op.create_table(
            'approval_request',
            sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
            sa.Column('tenant_id', sa.Integer, nullable=False, server_default='1'),
            sa.Column('request_type', sa.String(length=64), nullable=False),
            sa.Column('status', sa.String(length=32), nullable=False, server_default='pending_review'),
            sa.Column('review_mode', sa.String(length=32), nullable=False, server_default='first_response_wins'),
            sa.Column('space_id', sa.Integer, nullable=False),
            sa.Column('department_id', sa.Integer, nullable=False),
            sa.Column('parent_folder_id', sa.Integer, nullable=True),
            sa.Column('applicant_user_id', sa.Integer, nullable=False),
            sa.Column('applicant_user_name', sa.String(length=255), nullable=False, server_default=''),
            sa.Column('reviewer_user_ids', sa.JSON(), nullable=True),
            sa.Column('file_count', sa.Integer, nullable=False, server_default='0'),
            sa.Column('payload_json', sa.JSON(), nullable=False),
            sa.Column('safety_status', sa.String(length=32), nullable=False, server_default='skipped'),
            sa.Column('safety_reason', sa.Text(), nullable=True),
            sa.Column('decision_reason', sa.Text(), nullable=True),
            sa.Column('decided_by', sa.Integer, nullable=True),
            sa.Column('decided_at', sa.DateTime(), nullable=True),
            sa.Column('finalized_at', sa.DateTime(), nullable=True),
            sa.Column('message_id', sa.Integer, nullable=True),
            sa.Column('create_time', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.Column('update_time', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')),
        )
        op.create_index('idx_approval_request_status', 'approval_request', ['status'])
        op.create_index('idx_approval_request_space_id', 'approval_request', ['space_id'])
        op.create_index('idx_approval_request_department_id', 'approval_request', ['department_id'])
        op.create_index('idx_approval_request_applicant', 'approval_request', ['applicant_user_id'])
        op.create_index('idx_approval_request_message_id', 'approval_request', ['message_id'])
    else:
        for index_name, columns in (
            ('idx_approval_request_status', ['status']),
            ('idx_approval_request_space_id', ['space_id']),
            ('idx_approval_request_department_id', ['department_id']),
            ('idx_approval_request_applicant', ['applicant_user_id']),
            ('idx_approval_request_message_id', ['message_id']),
        ):
            if not _index_exists('approval_request', index_name):
                op.create_index(index_name, 'approval_request', columns)


def downgrade() -> None:
    if _table_exists('approval_request'):
        for index_name in (
            'idx_approval_request_status',
            'idx_approval_request_space_id',
            'idx_approval_request_department_id',
            'idx_approval_request_applicant',
            'idx_approval_request_message_id',
        ):
            if _index_exists('approval_request', index_name):
                op.drop_index(index_name, table_name='approval_request')
        op.drop_table('approval_request')
