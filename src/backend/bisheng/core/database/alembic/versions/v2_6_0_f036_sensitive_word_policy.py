"""F036: tenant-scoped sensitive word policy.

Revision ID: f036_sensitive_word_policy
Revises: f035_user_tenant_subtree_cleanup
Create Date: 2026-05-12
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import CLOB
from sqlalchemy.dialects import mysql

from bisheng.core.database.alembic_helpers.online import table_exists

revision: str = 'f036_sensitive_word_policy'
down_revision: Union[str, Sequence[str], None] = 'f035_user_tenant_subtree_cleanup'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = 'sensitive_word_policy'


def upgrade() -> None:
    if table_exists(_TABLE):
        return

    json_type = sa.Text().with_variant(mysql.JSON(), 'mysql').with_variant(CLOB(), 'dm')
    large_text = sa.Text().with_variant(mysql.LONGTEXT(), 'mysql').with_variant(CLOB(), 'dm')
    op.create_table(
        _TABLE,
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('tenant_id', sa.Integer, nullable=False, comment='租户ID'),
        sa.Column('business_type', sa.String(length=64), nullable=False, comment='业务场景'),
        sa.Column('scope_type', sa.String(length=32), nullable=False, server_default=sa.text("'tenant'"), comment='作用域类型'),
        sa.Column('scope_id', sa.String(length=64), nullable=False, comment='作用域ID'),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text('0'), comment='是否启用'),
        sa.Column('words_types', json_type, nullable=True, comment='词表类型：builtin/custom'),
        sa.Column('custom_words', large_text, nullable=False, comment='自定义词表内容'),
        sa.Column('auto_reply', sa.String(length=500), nullable=False, server_default=sa.text("''"), comment='命中提示话术'),
        sa.Column('extra_config', json_type, nullable=True, comment='扩展配置'),
        sa.Column('created_by', sa.Integer, nullable=True, comment='创建人ID'),
        sa.Column('updated_by', sa.Integer, nullable=True, comment='更新人ID'),
        sa.Column('create_time', sa.DateTime, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('update_time', sa.DateTime, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP'), onupdate=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('logic_delete', sa.Integer, nullable=False, server_default=sa.text('0'), comment='逻辑删除标记'),
        sa.UniqueConstraint(
            'tenant_id',
            'business_type',
            'scope_type',
            'scope_id',
            'logic_delete',
            name='uk_sensitive_policy_scope',
        ),
        mysql_charset='utf8mb4',
        mysql_collate='utf8mb4_unicode_ci',
    )
    op.create_index('ix_sensitive_word_policy_tenant_id', _TABLE, ['tenant_id'])
    op.create_index('ix_sensitive_word_policy_business_type', _TABLE, ['business_type'])
    op.create_index('ix_sensitive_word_policy_scope_id', _TABLE, ['scope_id'])


def downgrade() -> None:
    if not table_exists(_TABLE):
        return
    op.drop_index('ix_sensitive_word_policy_scope_id', table_name=_TABLE)
    op.drop_index('ix_sensitive_word_policy_business_type', table_name=_TABLE)
    op.drop_index('ix_sensitive_word_policy_tenant_id', table_name=_TABLE)
    op.drop_table(_TABLE)
