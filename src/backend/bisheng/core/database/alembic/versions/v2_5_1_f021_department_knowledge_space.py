"""F021: add department knowledge space bindings and SCM membership_source.

Revision ID: f021_department_knowledge_space
Revises: f020_llm_tenant
Create Date: 2026-04-21
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f021_department_knowledge_space'
down_revision: Union[str, Sequence[str], None] = 'f020_llm_tenant'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(sa.text(
        'SELECT COUNT(*) FROM information_schema.TABLES '
        'WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t'
    ), {'t': name})
    return result.scalar() > 0


def _column_exists(table_name: str, column_name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(sa.text(
        'SELECT COUNT(*) FROM information_schema.COLUMNS '
        'WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t AND COLUMN_NAME = :c'
    ), {'t': table_name, 'c': column_name})
    return result.scalar() > 0


def _index_exists(table_name: str, index_name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(sa.text(
        'SELECT COUNT(*) FROM information_schema.STATISTICS '
        'WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t AND INDEX_NAME = :i'
    ), {'t': table_name, 'i': index_name})
    return result.scalar() > 0


def upgrade() -> None:
    if not _table_exists('department_knowledge_space'):
        op.create_table(
            'department_knowledge_space',
            sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
            sa.Column('tenant_id', sa.Integer, nullable=False, server_default='1'),
            sa.Column('department_id', sa.Integer, sa.ForeignKey('department.id', ondelete='CASCADE'), nullable=False),
            sa.Column('space_id', sa.Integer, sa.ForeignKey('knowledge.id', ondelete='CASCADE'), nullable=False),
            sa.Column('created_by', sa.Integer, nullable=False, server_default='0'),
            sa.Column('create_time', sa.DateTime, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.Column('update_time', sa.DateTime, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')),
            sa.UniqueConstraint('department_id', name='uk_dks_department_id'),
            sa.UniqueConstraint('space_id', name='uk_dks_space_id'),
        )
        op.create_index('idx_dks_tenant_id', 'department_knowledge_space', ['tenant_id'])
        op.create_index('idx_dks_department_id', 'department_knowledge_space', ['department_id'])
        op.create_index('idx_dks_space_id', 'department_knowledge_space', ['space_id'])
    else:
        if not _index_exists('department_knowledge_space', 'idx_dks_tenant_id'):
            op.create_index('idx_dks_tenant_id', 'department_knowledge_space', ['tenant_id'])
        if not _index_exists('department_knowledge_space', 'idx_dks_department_id'):
            op.create_index('idx_dks_department_id', 'department_knowledge_space', ['department_id'])
        if not _index_exists('department_knowledge_space', 'idx_dks_space_id'):
            op.create_index('idx_dks_space_id', 'department_knowledge_space', ['space_id'])

    if not _column_exists('space_channel_member', 'membership_source'):
        op.add_column(
            'space_channel_member',
            sa.Column(
                'membership_source',
                sa.String(length=32),
                nullable=False,
                server_default='manual',
                comment='manual | department_admin',
            ),
        )


def downgrade() -> None:
    if _column_exists('space_channel_member', 'membership_source'):
        op.drop_column('space_channel_member', 'membership_source')

    if _table_exists('department_knowledge_space'):
        if _index_exists('department_knowledge_space', 'idx_dks_tenant_id'):
            op.drop_index('idx_dks_tenant_id', table_name='department_knowledge_space')
        if _index_exists('department_knowledge_space', 'idx_dks_department_id'):
            op.drop_index('idx_dks_department_id', table_name='department_knowledge_space')
        if _index_exists('department_knowledge_space', 'idx_dks_space_id'):
            op.drop_index('idx_dks_space_id', table_name='department_knowledge_space')
        op.drop_table('department_knowledge_space')
