"""F015: org_sync_log event fields + composite conflict index.

Revision ID: f015_reconcile_log_fields
Revises: f014_sso_sync_fields
Create Date: 2026-04-22

Changes:
  - ALTER org_sync_log ADD COLUMN event_type VARCHAR(32) NOT NULL DEFAULT ''.
    Distinguishes the F009 batch-summary rows (`event_type=''`) from the
    F015 event-scoped rows (`ts_conflict`, `stale_ts`,
    `conflict_weekly_sent`, `conflict_daily_escalation_sent`).
  - ALTER org_sync_log ADD COLUMN level VARCHAR(16) NOT NULL DEFAULT 'info'.
    Log severity for event rows (info / warn / error). Legacy batch-summary
    rows keep the default 'info' value; the F009 reader does not inspect it.
  - ALTER org_sync_log ADD COLUMN external_id VARCHAR(128) NULL.
    Department external_id tied to an event row (null on batch-summary rows).
    Used by `acount_recent_conflicts` for the weekly-report threshold check.
  - ALTER org_sync_log ADD COLUMN source_ts BIGINT NULL.
    Captures the incoming ts value that drove the event (INV-T12 audit).
  - CREATE INDEX idx_conflict_lookup ON org_sync_log
    (level, event_type, external_id, create_time).
    Serves the weekly conflict aggregation SQL (spec §5.5.3).

Idempotent: every step is guarded by an existence check, consistent with
F011/F012/F014 pattern.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f015_reconcile_log_fields'
down_revision: Union[str, Sequence[str], None] = 'f014_sso_sync_fields'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table_name: str, column_name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            'SELECT COUNT(*) FROM information_schema.COLUMNS '
            'WHERE TABLE_SCHEMA = DATABASE() '
            '  AND TABLE_NAME = :t AND COLUMN_NAME = :c'
        ),
        {'t': table_name, 'c': column_name},
    )
    return result.scalar() > 0


def _index_exists(table_name: str, index_name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            'SELECT COUNT(*) FROM information_schema.STATISTICS '
            'WHERE TABLE_SCHEMA = DATABASE() '
            '  AND TABLE_NAME = :t AND INDEX_NAME = :i'
        ),
        {'t': table_name, 'i': index_name},
    )
    return result.scalar() > 0


def upgrade() -> None:
    # -- org_sync_log.event_type --
    if not _column_exists('org_sync_log', 'event_type'):
        op.add_column(
            'org_sync_log',
            sa.Column(
                'event_type',
                sa.String(32),
                nullable=False,
                server_default='',
                comment=(
                    "F015: '' for batch-summary rows (F009), "
                    'ts_conflict/stale_ts/conflict_weekly_sent/... for event rows'
                ),
            ),
        )

    # -- org_sync_log.level --
    if not _column_exists('org_sync_log', 'level'):
        op.add_column(
            'org_sync_log',
            sa.Column(
                'level',
                sa.String(16),
                nullable=False,
                server_default='info',
                comment='F015: log severity (info / warn / error)',
            ),
        )

    # -- org_sync_log.external_id --
    if not _column_exists('org_sync_log', 'external_id'):
        op.add_column(
            'org_sync_log',
            sa.Column(
                'external_id',
                sa.String(128),
                nullable=True,
                comment='F015: department external_id for event rows',
            ),
        )

    # -- org_sync_log.source_ts --
    if not _column_exists('org_sync_log', 'source_ts'):
        op.add_column(
            'org_sync_log',
            sa.Column(
                'source_ts',
                sa.BigInteger,
                nullable=True,
                comment='F015: incoming ts captured for INV-T12 audit',
            ),
        )

    # -- composite index serving the weekly conflict aggregation SQL --
    if not _index_exists('org_sync_log', 'idx_conflict_lookup'):
        op.create_index(
            'idx_conflict_lookup',
            'org_sync_log',
            ['level', 'event_type', 'external_id', 'create_time'],
        )


def downgrade() -> None:
    if _index_exists('org_sync_log', 'idx_conflict_lookup'):
        op.drop_index('idx_conflict_lookup', table_name='org_sync_log')
    if _column_exists('org_sync_log', 'source_ts'):
        op.drop_column('org_sync_log', 'source_ts')
    if _column_exists('org_sync_log', 'external_id'):
        op.drop_column('org_sync_log', 'external_id')
    if _column_exists('org_sync_log', 'level'):
        op.drop_column('org_sync_log', 'level')
    if _column_exists('org_sync_log', 'event_type'):
        op.drop_column('org_sync_log', 'event_type')
