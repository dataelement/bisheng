"""F009: Create org_sync_config, org_sync_log tables and extend user table.

Revision ID: f009_org_sync
Revises: f005_role_menu_quota
Create Date: 2026-04-13

Changes:
  - CREATE TABLE org_sync_config (sync configuration per provider)
  - CREATE TABLE org_sync_log (sync execution history)
  - ALTER TABLE user ADD COLUMN source VARCHAR(32) NOT NULL DEFAULT 'local'
  - ALTER TABLE user ADD COLUMN external_id VARCHAR(128) NULL
  - CREATE UNIQUE INDEX uk_user_source_external_id ON user(source, external_id)
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f009_org_sync'
down_revision: Union[str, Sequence[str], None] = 'f005_role_menu_quota'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT COUNT(*) FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t"
    ), {'t': table_name})
    return result.scalar() > 0


def _column_exists(table_name: str, column_name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT COUNT(*) FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t AND COLUMN_NAME = :c"
    ), {'t': table_name, 'c': column_name})
    return result.scalar() > 0


def _index_exists(table_name: str, index_name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT COUNT(*) FROM information_schema.STATISTICS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t AND INDEX_NAME = :i"
    ), {'t': table_name, 'i': index_name})
    return result.scalar() > 0


def upgrade() -> None:
    # -- org_sync_config --
    if not _table_exists('org_sync_config'):
        op.create_table(
            'org_sync_config',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('tenant_id', sa.Integer, nullable=False, server_default='1',
                  comment='Tenant ID'),
        sa.Column('provider', sa.String(32), nullable=False,
                  comment='Provider: feishu/wecom/dingtalk/generic_api'),
        sa.Column('config_name', sa.String(128), nullable=False,
                  comment='User-given label'),
        sa.Column('auth_type', sa.String(16), nullable=False,
                  comment='Auth mode: api_key/password'),
        sa.Column('auth_config', sa.Text, nullable=False,
                  comment='Fernet-encrypted JSON'),
        sa.Column('sync_scope', sa.JSON, nullable=True,
                  comment='Sync scope JSON'),
        sa.Column('schedule_type', sa.String(16), nullable=False,
                  server_default='manual', comment='manual/cron'),
        sa.Column('cron_expression', sa.String(64), nullable=True,
                  comment='Cron expression'),
        sa.Column('sync_status', sa.String(16), nullable=False,
                  server_default='idle', comment='Runtime mutex: idle/running'),
        sa.Column('last_sync_at', sa.DateTime, nullable=True,
                  comment='Last sync time'),
        sa.Column('last_sync_result', sa.String(16), nullable=True,
                  comment='success/partial/failed'),
        sa.Column('status', sa.String(16), nullable=False,
                  server_default='active', comment='active/disabled/deleted'),
        sa.Column('create_user', sa.Integer, nullable=True,
                  comment='Creator user ID'),
        sa.Column('create_time', sa.DateTime, nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('update_time', sa.DateTime, nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')),
        )
        op.create_index('idx_osc_tenant', 'org_sync_config', ['tenant_id'])
        op.create_index('idx_osc_status', 'org_sync_config', ['status'])
        op.create_unique_constraint(
            'uk_tenant_provider_name', 'org_sync_config',
            ['tenant_id', 'provider', 'config_name'],
        )

    # -- org_sync_log --
    if not _table_exists('org_sync_log'):
        op.create_table(
            'org_sync_log',
            sa.Column('id', sa.BigInteger, primary_key=True, autoincrement=True),
            sa.Column('tenant_id', sa.Integer, nullable=False, server_default='1'),
            sa.Column('config_id', sa.Integer, nullable=False,
                      comment='FK to org_sync_config.id'),
            sa.Column('trigger_type', sa.String(16), nullable=False,
                      comment='manual/scheduled'),
            sa.Column('trigger_user', sa.Integer, nullable=True,
                      comment='User who triggered'),
            sa.Column('status', sa.String(16), nullable=False,
                      server_default='running',
                      comment='running/success/partial/failed'),
            sa.Column('dept_created', sa.Integer, nullable=False, server_default='0'),
            sa.Column('dept_updated', sa.Integer, nullable=False, server_default='0'),
            sa.Column('dept_archived', sa.Integer, nullable=False, server_default='0'),
            sa.Column('member_created', sa.Integer, nullable=False, server_default='0'),
            sa.Column('member_updated', sa.Integer, nullable=False, server_default='0'),
            sa.Column('member_disabled', sa.Integer, nullable=False, server_default='0'),
            sa.Column('member_reactivated', sa.Integer, nullable=False, server_default='0'),
            sa.Column('error_details', sa.JSON, nullable=True,
                      comment='Error list JSON'),
            sa.Column('start_time', sa.DateTime, nullable=True),
            sa.Column('end_time', sa.DateTime, nullable=True),
            sa.Column('create_time', sa.DateTime, nullable=False,
                      server_default=sa.text('CURRENT_TIMESTAMP')),
        )
        op.create_index('idx_osl_tenant', 'org_sync_log', ['tenant_id'])
        op.create_index('idx_osl_config', 'org_sync_log', ['config_id'])

    # -- user table extension --
    if not _column_exists('user', 'source'):
        op.add_column('user', sa.Column(
            'source', sa.String(32), nullable=False,
            server_default='local',
            comment='Source: local/feishu/wecom/dingtalk/generic_api',
        ))
    if not _column_exists('user', 'external_id'):
        op.add_column('user', sa.Column(
            'external_id', sa.String(128), nullable=True,
            comment='External employee ID for sync',
        ))
    if not _index_exists('user', 'uk_user_source_external_id'):
        op.create_unique_constraint(
            'uk_user_source_external_id', 'user',
            ['source', 'external_id'],
        )


def downgrade() -> None:
    # -- user table rollback --
    op.drop_constraint('uk_user_source_external_id', 'user', type_='unique')
    op.drop_column('user', 'external_id')
    op.drop_column('user', 'source')

    # -- org_sync_log --
    op.drop_index('idx_osl_config', table_name='org_sync_log')
    op.drop_index('idx_osl_tenant', table_name='org_sync_log')
    op.drop_table('org_sync_log')

    # -- org_sync_config --
    op.drop_constraint('uk_tenant_provider_name', 'org_sync_config', type_='unique')
    op.drop_index('idx_osc_status', table_name='org_sync_config')
    op.drop_index('idx_osc_tenant', table_name='org_sync_config')
    op.drop_table('org_sync_config')
