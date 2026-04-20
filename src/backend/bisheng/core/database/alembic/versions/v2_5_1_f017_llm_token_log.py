"""F017: create llm_token_log + llm_call_log tables — tenant-shared-storage.

Revision ID: f017_llm_token_log
Revises: f017_is_shared
Create Date: 2026-04-20

Changes:
  - CREATE TABLE llm_token_log — rows populated by LLMTokenTracker.record_usage
    on every LangChain on_llm_end callback. Feeds QuotaService's monthly
    token quota SQL template (previously degraded to 0).
  - CREATE TABLE llm_call_log — rows populated by ModelCallLogger.log on
    every call (success + error). Used for latency analytics and future
    cost accounting.

Both tables carry ``tenant_id`` as the first index-capable column per
INV-T13 so QuotaService / Tenant usage dashboards can scope efficiently.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f017_llm_token_log'
down_revision: Union[str, Sequence[str], None] = 'f017_is_shared'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(sa.text(
        'SELECT COUNT(*) FROM information_schema.TABLES '
        'WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t'
    ), {'t': name})
    return result.scalar() > 0


def upgrade() -> None:
    if not _table_exists('llm_token_log'):
        op.create_table(
            'llm_token_log',
            sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
            sa.Column('tenant_id', sa.Integer, nullable=False, server_default='1',
                      comment='F017 INV-T13: user leaf tenant at write time'),
            sa.Column('user_id', sa.Integer, nullable=False,
                      comment='Invoking user id'),
            sa.Column('model_id', sa.Integer, nullable=True, comment='llm_model.id'),
            sa.Column('server_id', sa.Integer, nullable=True, comment='llm_server.id'),
            sa.Column('session_id', sa.String(64), nullable=True,
                      comment='Originating chat session id (optional)'),
            sa.Column('prompt_tokens', sa.Integer, nullable=False, server_default='0'),
            sa.Column('completion_tokens', sa.Integer, nullable=False, server_default='0'),
            sa.Column('total_tokens', sa.Integer, nullable=False, server_default='0'),
            sa.Column('created_at', sa.DateTime, nullable=False,
                      server_default=sa.text('CURRENT_TIMESTAMP')),
        )
        # Composite index serves the F016 monthly sum:
        #   WHERE tenant_id = ? AND created_at >= '<month_start>'
        op.create_index(
            'idx_llm_token_log_tenant_created',
            'llm_token_log', ['tenant_id', 'created_at'],
        )
        op.create_index('idx_llm_token_log_user_id', 'llm_token_log', ['user_id'])
        op.create_index('idx_llm_token_log_model_id', 'llm_token_log', ['model_id'])
        op.create_index('idx_llm_token_log_server_id', 'llm_token_log', ['server_id'])

    if not _table_exists('llm_call_log'):
        op.create_table(
            'llm_call_log',
            sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
            sa.Column('tenant_id', sa.Integer, nullable=False, server_default='1',
                      comment='F017 INV-T13: user leaf tenant at write time'),
            sa.Column('user_id', sa.Integer, nullable=False),
            sa.Column('model_id', sa.Integer, nullable=True, comment='llm_model.id'),
            sa.Column('server_id', sa.Integer, nullable=True, comment='llm_server.id'),
            sa.Column('endpoint', sa.String(256), nullable=True,
                      comment='Request endpoint URL (for analytics, not secrets)'),
            sa.Column('status', sa.String(16), nullable=False,
                      comment='success | error'),
            sa.Column('latency_ms', sa.Integer, nullable=True),
            sa.Column('error_msg', sa.String(512), nullable=True,
                      comment='Truncated error string for failed calls'),
            sa.Column('created_at', sa.DateTime, nullable=False,
                      server_default=sa.text('CURRENT_TIMESTAMP')),
        )
        op.create_index(
            'idx_llm_call_log_tenant_created',
            'llm_call_log', ['tenant_id', 'created_at'],
        )
        op.create_index('idx_llm_call_log_user_id', 'llm_call_log', ['user_id'])
        op.create_index('idx_llm_call_log_status', 'llm_call_log', ['status'])


def downgrade() -> None:
    if _table_exists('llm_call_log'):
        op.drop_index('idx_llm_call_log_status', 'llm_call_log')
        op.drop_index('idx_llm_call_log_user_id', 'llm_call_log')
        op.drop_index('idx_llm_call_log_tenant_created', 'llm_call_log')
        op.drop_table('llm_call_log')
    if _table_exists('llm_token_log'):
        op.drop_index('idx_llm_token_log_server_id', 'llm_token_log')
        op.drop_index('idx_llm_token_log_model_id', 'llm_token_log')
        op.drop_index('idx_llm_token_log_user_id', 'llm_token_log')
        op.drop_index('idx_llm_token_log_tenant_created', 'llm_token_log')
        op.drop_table('llm_token_log')
