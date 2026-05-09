"""F034: add knowledge space scope table.

Revision ID: f034_knowledge_space_scope
Revises: f033_add_file_encoding
Create Date: 2026-05-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f034_knowledge_space_scope'
down_revision: Union[str, Sequence[str], None] = 'f033_add_file_encoding'
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
    if not _table_exists('knowledge_space_scope'):
        op.create_table(
            'knowledge_space_scope',
            sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
            sa.Column('tenant_id', sa.Integer, nullable=False, server_default='1'),
            sa.Column('space_id', sa.Integer, sa.ForeignKey('knowledge.id', ondelete='CASCADE'), nullable=False),
            sa.Column('level', sa.String(length=32), nullable=False),
            sa.Column('owner_type', sa.String(length=64), nullable=False),
            sa.Column('owner_id', sa.Integer, nullable=False),
            sa.Column('created_by', sa.Integer, nullable=False, server_default='0'),
            sa.Column('create_time', sa.DateTime, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.Column('update_time', sa.DateTime, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')),
            sa.UniqueConstraint('space_id', name='uk_kss_space_id'),
        )
        op.create_index('idx_kss_tenant_level', 'knowledge_space_scope', ['tenant_id', 'level'])
        op.create_index('idx_kss_tenant_owner', 'knowledge_space_scope', ['tenant_id', 'owner_type', 'owner_id'])
    else:
        if not _index_exists('knowledge_space_scope', 'idx_kss_tenant_level'):
            op.create_index('idx_kss_tenant_level', 'knowledge_space_scope', ['tenant_id', 'level'])
        if not _index_exists('knowledge_space_scope', 'idx_kss_tenant_owner'):
            op.create_index('idx_kss_tenant_owner', 'knowledge_space_scope', ['tenant_id', 'owner_type', 'owner_id'])

    conn = op.get_bind()
    conn.execute(sa.text("""
        INSERT INTO knowledge_space_scope
            (tenant_id, space_id, level, owner_type, owner_id, created_by)
        SELECT
            COALESCE(k.tenant_id, 1) AS tenant_id,
            k.id AS space_id,
            CASE WHEN dks.space_id IS NOT NULL THEN 'department' ELSE 'personal' END AS level,
            CASE WHEN dks.space_id IS NOT NULL THEN 'department' ELSE 'user' END AS owner_type,
            CASE WHEN dks.space_id IS NOT NULL THEN dks.department_id ELSE COALESCE(k.user_id, 0) END AS owner_id,
            COALESCE(k.user_id, 0) AS created_by
        FROM knowledge k
        LEFT JOIN department_knowledge_space dks ON dks.space_id = k.id
        LEFT JOIN knowledge_space_scope existing ON existing.space_id = k.id
        WHERE k.type = 3
          AND existing.id IS NULL
    """))


def downgrade() -> None:
    if not _table_exists('knowledge_space_scope'):
        return
    if _index_exists('knowledge_space_scope', 'idx_kss_tenant_level'):
        op.drop_index('idx_kss_tenant_level', table_name='knowledge_space_scope')
    if _index_exists('knowledge_space_scope', 'idx_kss_tenant_owner'):
        op.drop_index('idx_kss_tenant_owner', table_name='knowledge_space_scope')
    op.drop_table('knowledge_space_scope')
