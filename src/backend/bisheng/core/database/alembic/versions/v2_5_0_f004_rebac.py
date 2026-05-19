"""F004: Create failed_tuple table for OpenFGA compensation queue.

Revision ID: f004_rebac
Revises: f003_user_group
Create Date: 2026-04-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import index_exists, table_exists, update_time_server_default

revision: str = 'f004_rebac'
down_revision: Union[str, Sequence[str], None] = 'f003_user_group'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    """Create failed_tuple table."""
    conn = op.get_bind()
    if not table_exists(conn, 'failed_tuple'):
        op.create_table(
            'failed_tuple',
            sa.Column('id', sa.BigInteger, primary_key=True, autoincrement=True),
            sa.Column('action', sa.String(8), nullable=False, server_default='write',
                      comment='write | delete'),
            sa.Column('fga_user', sa.String(256), nullable=False,
                      comment='OpenFGA user, e.g. user:7, department:5#member'),
            sa.Column('relation', sa.String(64), nullable=False,
                      comment='OpenFGA relation, e.g. owner, viewer'),
            sa.Column('object', sa.String(256), nullable=False,
                      comment='OpenFGA object, e.g. workflow:abc-123'),
            sa.Column('retry_count', sa.Integer, nullable=False, server_default='0'),
            sa.Column('max_retries', sa.Integer, nullable=False, server_default='3'),
            sa.Column('status', sa.String(16), nullable=False, server_default='pending',
                      comment='pending | succeeded | dead'),
            sa.Column('error_message', sa.Text, nullable=True),
            sa.Column('tenant_id', sa.Integer, nullable=False, server_default='1'),
            sa.Column('create_time', sa.DateTime, nullable=False,
                      server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.Column('update_time', sa.DateTime, nullable=False,
                      server_default=update_time_server_default(conn)),
        )
    if not index_exists(conn, 'failed_tuple', 'idx_status_retry'):
        op.create_index('idx_status_retry', 'failed_tuple', ['status', 'retry_count'])
    if not index_exists(conn, 'failed_tuple', 'idx_tenant'):
        op.create_index('idx_tenant', 'failed_tuple', ['tenant_id'])

def downgrade() -> None:
    """Drop failed_tuple table."""
    conn = op.get_bind()
    if index_exists(conn, 'failed_tuple', 'idx_tenant'):
        op.drop_index('idx_tenant', table_name='failed_tuple')
    if index_exists(conn, 'failed_tuple', 'idx_status_retry'):
        op.drop_index('idx_status_retry', table_name='failed_tuple')
    if table_exists(conn, 'failed_tuple'):
        op.drop_table('failed_tuple')
