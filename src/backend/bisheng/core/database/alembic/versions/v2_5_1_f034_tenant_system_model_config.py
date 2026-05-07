"""F034: tenant_system_model_config — split 5 system LLM defaults out of `config`.

Revision ID: f034_tenant_system_model_config
Revises: f033_add_file_encoding
Create Date: 2026-05-07

Why:
  v2.5.1 §F022 elevates the 5 system-level LLM default selections
  (knowledge_llm / assistant_llm / evaluation_llm / workflow_llm /
  linsight_llm) from globally-unique rows in ``config`` to per-tenant
  rows in ``tenant_system_model_config``, with Root-share fallback.
  See features/v2.5.1/022-llm-system-config-tenant-isolation/spec.md.

What:
  1) Create ``tenant_system_model_config`` if missing — a fresh DB
     gets the table from ``SQLModel.metadata.create_all()`` at app
     startup, so this guard prevents a duplicate-create error.
  2) Backfill the 5 keys from ``config`` to ``tenant_id=1`` using
     INSERT IGNORE so reruns are idempotent (AC-25 / AC-28).

Rollback:
  Drop the new table only. The original 5 ``config`` rows are kept
  as rollback anchors per AD-06; the service path switches over to
  the new table on upgrade and the orphaned rows do not affect
  downgrade behavior.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import LONGTEXT

from bisheng.common.models.config import ConfigKeyEnum
from bisheng.core.database.alembic_helpers.online import table_exists

revision: str = 'f034_tenant_system_model_config'
down_revision: Union[str, Sequence[str], None] = 'f033_add_file_encoding'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = 'tenant_system_model_config'
# Single source of truth for the 5 F022-managed config keys: the
# enum values defined alongside the legacy `config` table they're
# being migrated out of.
_KEYS = (
    ConfigKeyEnum.KNOWLEDGE_LLM.value,
    ConfigKeyEnum.ASSISTANT_LLM.value,
    ConfigKeyEnum.EVALUATION_LLM.value,
    ConfigKeyEnum.WORKFLOW_LLM.value,
    ConfigKeyEnum.LINSIGHT_LLM.value,
)
_ROOT_TENANT_ID = 1


def upgrade() -> None:
    if not table_exists(_TABLE):
        # ``LONGTEXT`` is MySQL-specific; ``with_variant(sa.Text(), 'sqlite')``
        # lets the same DDL compile in sqlite-backed test harnesses (the
        # production migration still emits LONGTEXT on MySQL).
        value_type = sa.Text().with_variant(LONGTEXT(), 'mysql')
        op.create_table(
            _TABLE,
            sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
            sa.Column(
                'tenant_id', sa.Integer, nullable=False,
                comment='Owner tenant; 1=Root, others=Child leaf',
            ),
            sa.Column(
                'key', sa.String(length=64), nullable=False,
                comment='ConfigKeyEnum value: linsight_llm/knowledge_llm/...',
            ),
            sa.Column(
                'value', value_type, nullable=True,
                comment='JSON-encoded config payload',
            ),
            sa.Column(
                'is_shared_to_children', sa.SmallInteger, nullable=True,
                comment='Reserved (v2.6+); NULL = use Tenant.share_default_to_children',
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
                name='uq_tenant_system_model_tenant_key',
            ),
            mysql_charset='utf8mb4',
            mysql_collate='utf8mb4_unicode_ci',
        )
        op.create_index(
            'ix_tenant_system_model_config_tenant_id', _TABLE, ['tenant_id'],
        )
        op.create_index(
            'ix_tenant_system_model_config_key', _TABLE, ['key'],
        )

    # Backfill the 5 keys from `config` to tenant_id=1. The SQL flavor
    # for "INSERT ... avoid duplicates" varies by dialect — MySQL uses
    # `INSERT IGNORE`, SQLite uses `INSERT OR IGNORE`. The dialect
    # branch keeps the migration runnable in sqlite-backed test
    # harnesses (see test_f034_tenant_system_model_config_migration.py)
    # without sacrificing the prod MySQL path. AC-28 (idempotency on
    # rerun) holds in both cases.
    if not table_exists('config'):
        return  # Fresh install before any global config exists.
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == 'mysql':
        insert_prefix = 'INSERT IGNORE INTO'
        key_quote = '`key`'
    elif dialect == 'sqlite':
        insert_prefix = 'INSERT OR IGNORE INTO'
        key_quote = '"key"'
    else:
        # Postgres / other backends are not v2.5 targets; bail loudly so
        # operators aren't silently left with an empty new table.
        raise NotImplementedError(
            f'F034 backfill: unsupported dialect {dialect!r}; '
            "extend _insert_ignore() to support it."
        )
    for key in _KEYS:
        bind.execute(
            sa.text(
                f"""
                {insert_prefix} tenant_system_model_config (tenant_id, {key_quote}, value)
                SELECT :tid, c.{key_quote}, c.value
                FROM config c
                WHERE c.{key_quote} = :key
                  AND c.value IS NOT NULL
                  AND c.value <> ''
                """
            ),
            {'tid': _ROOT_TENANT_ID, 'key': key},
        )


def downgrade() -> None:
    if table_exists(_TABLE):
        op.drop_index(
            'ix_tenant_system_model_config_key', table_name=_TABLE,
        )
        op.drop_index(
            'ix_tenant_system_model_config_tenant_id', table_name=_TABLE,
        )
        op.drop_table(_TABLE)
