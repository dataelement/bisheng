"""F001: Add multi-tenant infrastructure.

Creates tenant and user_tenant tables.
Adds tenant_id column to all business tables (INV-1).
Seeds default tenant (id=1) and backfills user_tenant associations.

Revision ID: f001_multi_tenant
Revises: 9ba42685e830
Create Date: 2026-04-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f001_multi_tenant'
down_revision: Union[str, Sequence[str], None] = '9ba42685e830'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# All business tables that need tenant_id (INV-1).
# Excluded: user, user_link, tenant, user_tenant, recallchunk, config,
#           space_channel_member (deprecated), failed_tuples, relation_definition
TENANT_TABLES = [
    # database/models/
    'flow',
    'flowversion',
    'assistant',
    'assistantlink',
    'tag',
    'taglink',
    'chatmessage',
    'message_session',
    't_report',
    't_variable_value',
    'template',
    'group',
    'groupresource',
    'role',
    'roleaccess',
    'usergroup',
    'evaluation',
    'dataset',
    'auditlog',
    'marktask',
    'markrecord',
    'markappuser',
    'invitecode',
    # knowledge DDD module
    'knowledge',
    'knowledgefile',
    'qaknowledge',
    # tool DDD module
    't_gpts_tools',
    't_gpts_tools_type',
    # channel DDD module
    'channel',
    'channel_info_source',
    'channel_article_read',
    # share_link DDD module
    'share_link',
    # message DDD module
    'inbox_message',
    'inbox_message_read',
    # finetune DDD module
    'finetune',
    'presettrain',
    'modeldeploy',
    'server',
    'sftmodel',
    # linsight DDD module
    'linsight_sop',
    'linsight_sop_record',
    'linsight_session_version',
    'linsight_execute_task',
    # llm DDD module
    'llm_server',
    'llm_model',
    # user DDD module
    'userrole',
]


def _table_exists(table_name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT COUNT(*) FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t"
        ),
        {"t": table_name},
    )
    return result.scalar() > 0


def _column_exists(table_name: str, column_name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT COUNT(*) FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() "
            "AND TABLE_NAME = :t AND COLUMN_NAME = :c"
        ),
        {"t": table_name, "c": column_name},
    )
    return result.scalar() > 0


def _index_exists(table_name: str, index_name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT COUNT(*) FROM information_schema.STATISTICS "
            "WHERE TABLE_SCHEMA = DATABASE() "
            "AND TABLE_NAME = :t AND INDEX_NAME = :i"
        ),
        {"t": table_name, "i": index_name},
    )
    return result.scalar() > 0


def upgrade() -> None:
    """Create tenant infrastructure and add tenant_id to business tables."""

    # 1. Create tenant table
    if not _table_exists('tenant'):
        op.create_table(
            'tenant',
            sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
            sa.Column('tenant_code', sa.String(64), nullable=False, unique=True, comment='Tenant code'),
            sa.Column('tenant_name', sa.String(128), nullable=False, comment='Tenant name'),
            sa.Column('logo', sa.String(512), nullable=True, comment='Tenant logo URL'),
            sa.Column('root_dept_id', sa.Integer, nullable=True, comment='Root department ID'),
            sa.Column('status', sa.String(16), nullable=False, server_default='active',
                      comment='Status: active/disabled/archived'),
            sa.Column('contact_name', sa.String(64), nullable=True, comment='Contact name'),
            sa.Column('contact_phone', sa.String(32), nullable=True, comment='Contact phone'),
            sa.Column('contact_email', sa.String(128), nullable=True, comment='Contact email'),
            sa.Column('quota_config', sa.JSON, nullable=True, comment='Tenant-level resource quota'),
            sa.Column('storage_config', sa.JSON, nullable=True, comment='Tenant-level storage config'),
            sa.Column('create_user', sa.Integer, nullable=True, comment='Created by user ID'),
            sa.Column('create_time', sa.DateTime, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.Column('update_time', sa.DateTime, nullable=False,
                      server_default=sa.text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')),
        )
    if not _index_exists('tenant', 'idx_tenant_status'):
        op.create_index('idx_tenant_status', 'tenant', ['status'])

    # 2. Create user_tenant table
    if not _table_exists('user_tenant'):
        op.create_table(
            'user_tenant',
            sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
            sa.Column('user_id', sa.Integer, nullable=False),
            sa.Column('tenant_id', sa.Integer, nullable=False),
            sa.Column('is_default', sa.Integer, nullable=False, server_default='0',
                      comment='Whether default tenant for user'),
            sa.Column('status', sa.String(16), nullable=False, server_default='active',
                      comment='Status: active/disabled'),
            sa.Column('last_access_time', sa.DateTime, nullable=True, comment='Last access time'),
            sa.Column('join_time', sa.DateTime, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        )
    if not _index_exists('user_tenant', 'idx_user_tenant_user_id'):
        op.create_index('idx_user_tenant_user_id', 'user_tenant', ['user_id'])
    if not _index_exists('user_tenant', 'idx_user_tenant_tenant_id'):
        op.create_index('idx_user_tenant_tenant_id', 'user_tenant', ['tenant_id'])
    if not _index_exists('user_tenant', 'uk_user_tenant') and not _index_exists('user_tenant', 'uk_user_active'):
        op.create_unique_constraint('uk_user_tenant', 'user_tenant', ['user_id', 'tenant_id'])

    # 3. Add tenant_id to all business tables
    for table_name in TENANT_TABLES:
        try:
            if not _table_exists(table_name):
                continue
            if not _column_exists(table_name, 'tenant_id'):
                op.add_column(
                    table_name,
                    sa.Column('tenant_id', sa.Integer, nullable=False, server_default='1',
                              comment='Tenant ID'),
                )
            if not _index_exists(table_name, f'idx_{table_name}_tenant_id'):
                op.create_index(f'idx_{table_name}_tenant_id', table_name, ['tenant_id'])
        except Exception as e:
            # Table may not exist in this deployment (e.g. linsight tables)
            print(f'WARNING: Failed to add tenant_id to {table_name}: {e}')

    # 4. Seed default tenant
    op.execute(
        "INSERT IGNORE INTO tenant (id, tenant_code, tenant_name, status) "
        "VALUES (1, 'default', 'Default Tenant', 'active')"
    )

    # 5. Backfill user_tenant for all existing users
    op.execute(
        "INSERT INTO user_tenant (user_id, tenant_id, is_default, status) "
        "SELECT u.user_id, 1, 1, 'active' FROM user u "
        "WHERE NOT EXISTS ("
        "  SELECT 1 FROM user_tenant ut "
        "  WHERE ut.user_id = u.user_id AND ut.tenant_id = 1"
        ")"
    )


def downgrade() -> None:
    """Remove tenant infrastructure. WARNING: loses tenant_id>1 data context."""

    # 1. Remove tenant_id from business tables (reverse order)
    for table_name in reversed(TENANT_TABLES):
        try:
            if _index_exists(table_name, f'idx_{table_name}_tenant_id'):
                op.drop_index(f'idx_{table_name}_tenant_id', table_name=table_name)
            if _column_exists(table_name, 'tenant_id'):
                op.drop_column(table_name, 'tenant_id')
        except Exception as e:
            print(f'WARNING: Failed to remove tenant_id from {table_name}: {e}')

    # 2. Drop user_tenant table
    if _table_exists('user_tenant'):
        op.drop_table('user_tenant')

    # 3. Drop tenant table
    if _table_exists('tenant'):
        op.drop_table('tenant')
