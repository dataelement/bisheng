"""F036: tenant_workstation_config — tenant-scoped workstation tab configs.

Revision ID: f036_tenant_workstation_config
Revises: f035_user_tenant_subtree_cleanup
Create Date: 2026-05-12

Why:
  Workstation tab configuration (daily / linsight / subscription /
  knowledge_space) currently lives in the global ``config`` table, so
  Child tenants overwrite each other and cannot keep tenant-local
  overrides. F036 introduces a dedicated tenant-scoped table. Business
  data migration intentionally stays outside Alembic and is handled by
  scripts/.

What:
  Create ``tenant_workstation_config`` if missing, with unique key
  ``(tenant_id, key)`` and supporting indexes.

Rollback:
  Drop the new table only. Legacy ``config`` rows remain intact.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import table_exists

revision: str = 'f036_tenant_workstation_config'
down_revision: Union[str, Sequence[str], None] = 'f035_user_tenant_subtree_cleanup'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = 'tenant_workstation_config'


def upgrade() -> None:
    if table_exists(_TABLE):
        return
    op.create_table(
        _TABLE,
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            'tenant_id', sa.Integer, nullable=False,
            comment='Owner tenant; 1=Root, others=Child leaf',
        ),
        sa.Column(
            'key', sa.String(length=64), nullable=False,
            comment='ConfigKeyEnum value: workstation/workstation_linsight/...',
        ),
        sa.Column(
            'value', sa.Text(), nullable=True,
            comment='JSON-encoded workstation config payload',
        ),
        sa.Column(
            'create_time', sa.DateTime, nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
        ),
        sa.Column(
            'update_time', sa.DateTime, nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
            onupdate=sa.text('CURRENT_TIMESTAMP'),
        ),
        sa.UniqueConstraint(
            'tenant_id', 'key',
            name='uq_tenant_workstation_tenant_key',
        ),
        mysql_charset='utf8mb4',
        mysql_collate='utf8mb4_unicode_ci',
    )
    op.create_index(
        'ix_tenant_workstation_config_tenant_id', _TABLE, ['tenant_id'],
    )
    op.create_index(
        'ix_tenant_workstation_config_key', _TABLE, ['key'],
    )


def downgrade() -> None:
    if not table_exists(_TABLE):
        return
    op.drop_index('ix_tenant_workstation_config_key', table_name=_TABLE)
    op.drop_index('ix_tenant_workstation_config_tenant_id', table_name=_TABLE)
    op.drop_table(_TABLE)
