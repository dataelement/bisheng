"""F014: department.is_deleted + department.last_sync_ts + SSO seed config.

Revision ID: f014_sso_sync_fields
Revises: f013_auditlog_tenant_id_nullable
Create Date: 2026-04-21

Changes:
  - ALTER department ADD COLUMN is_deleted TINYINT NOT NULL DEFAULT 0.
    Distinguishes "authoritatively removed by SSO/HR source of truth" from
    F009's reversible archive. Only consumed by OrgSyncTsGuard (INV-T12) and
    F015 Celery reconciliation — existing queries rely on `status='active'`
    for visibility and are unaffected.
  - ALTER department ADD COLUMN last_sync_ts BIGINT NOT NULL DEFAULT 0,
    indexed. Per-external_id high-water mark used by OrgSyncTsGuard so that
    Gateway realtime sync (F014) and Celery reconciliation (F015) converge
    on "ts max wins; same ts with upsert vs remove → remove wins".
  - INSERT into org_sync_config a fixed-id (9999) synthetic row tagged
    `provider='sso_realtime'`, `sync_status='disabled'`. F014 writes every
    SSO sync log row (`/internal/sso/login-sync` + `/departments/sync`)
    under this config_id so the org_sync management UI can still join back
    through the existing config_id → provider lookup.

Idempotent: every step is guarded by an existence check, consistent with
F011/F012 pattern.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import column_exists, index_exists

revision: str = 'f014_sso_sync_fields'
down_revision: Union[str, Sequence[str], None] = 'f013_auditlog_tenant_id_nullable'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SSO_SEED_CONFIG_ID = 9999
SSO_SEED_TENANT_ID = 1
SSO_SEED_PROVIDER = 'sso_realtime'
SSO_SEED_CONFIG_NAME = 'SSO Gateway (internal)'

def _seed_exists() -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text('SELECT COUNT(*) FROM org_sync_config WHERE id = :id'),
        {'id': SSO_SEED_CONFIG_ID},
    )
    return result.scalar() > 0

def upgrade() -> None:
    conn = op.get_bind()
    # -- department.is_deleted --
    if not column_exists(conn, 'department', 'is_deleted'):
        op.add_column(
            'department',
            sa.Column(
                'is_deleted',
                sa.SmallInteger,
                nullable=False,
                server_default='0',
                comment='F014: 1=removed by SSO authoritative source; 0=active or reversibly archived',
            ),
        )

    # -- department.last_sync_ts --
    if not column_exists(conn, 'department', 'last_sync_ts'):
        op.add_column(
            'department',
            sa.Column(
                'last_sync_ts',
                sa.BigInteger,
                nullable=False,
                server_default='0',
                comment='F014/F015 INV-T12: high-water mark of the latest Gateway/Celery sync',
            ),
        )
    if not index_exists(conn, 'department', 'idx_department_last_sync_ts'):
        op.create_index(
            'idx_department_last_sync_ts', 'department', ['last_sync_ts'],
        )

    # -- seed row for SSO realtime logs --
    if not _seed_exists():
        conn = op.get_bind()
        conn.execute(
            sa.text(
                'INSERT INTO org_sync_config '
                '(id, tenant_id, provider, config_name, auth_type, auth_config, '
                ' sync_scope, schedule_type, sync_status, status, '
                ' create_time, update_time) '
                'VALUES '
                '(:id, :tenant_id, :provider, :config_name, :auth_type, :auth_config, '
                ' :sync_scope, :schedule_type, :sync_status, :status, '
                ' CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)'
            ),
            {
                'id': SSO_SEED_CONFIG_ID,
                'tenant_id': SSO_SEED_TENANT_ID,
                'provider': SSO_SEED_PROVIDER,
                'config_name': SSO_SEED_CONFIG_NAME,
                'auth_type': 'hmac',
                'auth_config': '',
                'sync_scope': None,
                'schedule_type': 'manual',
                'sync_status': 'disabled',
                'status': 'active',
            },
        )

def downgrade() -> None:
    if _seed_exists():
        conn = op.get_bind()
        conn.execute(
            sa.text('DELETE FROM org_sync_config WHERE id = :id'),
            {'id': SSO_SEED_CONFIG_ID},
        )

    if index_exists(conn, 'department', 'idx_department_last_sync_ts'):
        op.drop_index('idx_department_last_sync_ts', table_name='department')
    if column_exists(conn, 'department', 'last_sync_ts'):
        op.drop_column('department', 'last_sync_ts')
    if column_exists(conn, 'department', 'is_deleted'):
        op.drop_column('department', 'is_deleted')
