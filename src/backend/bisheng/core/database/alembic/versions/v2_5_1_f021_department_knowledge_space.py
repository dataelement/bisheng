"""F021: add department knowledge space bindings and SCM membership_source.

Revision ID: f021_department_knowledge_space
Revises: f020_llm_tenant
Create Date: 2026-04-21
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import column_exists, index_exists, table_exists, update_time_server_default

revision: str = 'f021_department_knowledge_space'
down_revision: Union[str, Sequence[str], None] = 'f020_llm_tenant'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    conn = op.get_bind()
    if not table_exists(conn, 'department_knowledge_space'):
        op.create_table(
            'department_knowledge_space',
            sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
            sa.Column('tenant_id', sa.Integer, nullable=False, server_default='1'),
            sa.Column('department_id', sa.Integer, sa.ForeignKey('department.id', ondelete='CASCADE'), nullable=False),
            sa.Column('space_id', sa.Integer, sa.ForeignKey('knowledge.id', ondelete='CASCADE'), nullable=False),
            sa.Column('created_by', sa.Integer, nullable=False, server_default='0'),
            sa.Column('create_time', sa.DateTime, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.Column('update_time', sa.DateTime, nullable=False, server_default=update_time_server_default(conn)),
            sa.UniqueConstraint('department_id', name='uk_dks_department_id'),
            sa.UniqueConstraint('space_id', name='uk_dks_space_id'),
        )
        op.create_index('idx_dks_tenant_id', 'department_knowledge_space', ['tenant_id'])
        op.create_index('idx_dks_department_id', 'department_knowledge_space', ['department_id'])
        op.create_index('idx_dks_space_id', 'department_knowledge_space', ['space_id'])
    else:
        if not index_exists(conn, 'department_knowledge_space', 'idx_dks_tenant_id'):
            op.create_index('idx_dks_tenant_id', 'department_knowledge_space', ['tenant_id'])
        if not index_exists(conn, 'department_knowledge_space', 'idx_dks_department_id'):
            op.create_index('idx_dks_department_id', 'department_knowledge_space', ['department_id'])
        if not index_exists(conn, 'department_knowledge_space', 'idx_dks_space_id'):
            op.create_index('idx_dks_space_id', 'department_knowledge_space', ['space_id'])

    if not column_exists(conn, 'space_channel_member', 'membership_source'):
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
    conn = op.get_bind()
    if column_exists(conn, 'space_channel_member', 'membership_source'):
        op.drop_column('space_channel_member', 'membership_source')

    if table_exists(conn, 'department_knowledge_space'):
        if index_exists(conn, 'department_knowledge_space', 'idx_dks_tenant_id'):
            op.drop_index('idx_dks_tenant_id', table_name='department_knowledge_space')
        if index_exists(conn, 'department_knowledge_space', 'idx_dks_department_id'):
            op.drop_index('idx_dks_department_id', table_name='department_knowledge_space')
        if index_exists(conn, 'department_knowledge_space', 'idx_dks_space_id'):
            op.drop_index('idx_dks_space_id', table_name='department_knowledge_space')
        op.drop_table('department_knowledge_space')
