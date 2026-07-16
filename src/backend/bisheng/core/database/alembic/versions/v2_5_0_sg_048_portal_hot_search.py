"""F048: portal home hot-search snapshot, batch run and candidate diagnostics.

Revision ID: v2_5_0_sg_048_portal_hot_search
Revises: v2_5_0_sg_f056_portal_recommendation
Create Date: 2026-07-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import (
    LargeText,
    index_exists,
    table_exists,
)

revision: str = "v2_5_0_sg_048_portal_hot_search"
down_revision: str | Sequence[str] | None = "v2_5_0_sg_f056_portal_recommendation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SNAPSHOT_TABLE = "portal_hot_search_snapshot"
_BATCH_RUN_TABLE = "portal_hot_search_batch_run"
_CANDIDATE_TABLE = "portal_hot_search_candidate"

_SNAPSHOT_INDEXES = {
    "ix_phss_tenant_batch": ["tenant_id", "batch_id"],
    "ix_phss_tenant_rank": ["tenant_id", "rank_no"],
}
_BATCH_RUN_INDEXES = {
    "ix_phsbr_tenant_time": ["tenant_id", "computed_at"],
    "ix_phsbr_tenant_batch": ["tenant_id", "batch_id"],
}
_CANDIDATE_INDEXES = {
    "ix_phsc_tenant_batch": ["tenant_id", "batch_id"],
}


def _tenant_id_column() -> sa.Column:
    return sa.Column(
        "tenant_id",
        sa.Integer(),
        nullable=False,
        server_default=sa.text("1"),
        comment="Tenant ID",
    )


def _create_snapshot_table() -> None:
    op.create_table(
        _SNAPSHOT_TABLE,
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        _tenant_id_column(),
        sa.Column("rank_no", sa.SmallInteger(), nullable=False, comment="Rank 1-5"),
        sa.Column("intent_key", sa.String(length=64), nullable=False, comment="Intent group hash"),
        sa.Column("display_query", sa.String(length=100), nullable=False, comment="Rewritten question"),
        sa.Column("canonical_query", sa.String(length=100), nullable=False, comment="Intent representative query"),
        sa.Column("heat_score", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("unique_users", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("search_count_7d", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("search_count_8_30d", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("batch_id", sa.String(length=32), nullable=False, comment="{yyyymmdd}-{seq}"),
        sa.Column("computed_at", sa.DateTime(), nullable=False),
        sa.Column(
            "create_time",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )


def _create_batch_run_table() -> None:
    op.create_table(
        _BATCH_RUN_TABLE,
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        _tenant_id_column(),
        sa.Column("batch_id", sa.String(length=32), nullable=False, comment="{yyyymmdd}-{seq}"),
        sa.Column("status", sa.String(length=16), nullable=False, comment="running/success/failed/degraded"),
        sa.Column("window_start", sa.DateTime(), nullable=False),
        sa.Column("window_end", sa.DateTime(), nullable=False),
        sa.Column("scanned_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("distinct_query_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("candidate_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("dedup_record_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("qualified_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("llm_group_calls", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("llm_rewrite_calls", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("llm_degraded", sa.SmallInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("truncated", sa.SmallInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("es_pages", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("computed_at", sa.DateTime(), nullable=False),
        sa.Column(
            "create_time",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )


def _create_candidate_table() -> None:
    op.create_table(
        _CANDIDATE_TABLE,
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        _tenant_id_column(),
        sa.Column("batch_id", sa.String(length=32), nullable=False, comment="{yyyymmdd}-{seq}"),
        sa.Column("intent_key", sa.String(length=64), nullable=False),
        sa.Column("canonical_query", sa.String(length=100), nullable=False),
        sa.Column("display_query", sa.String(length=100), nullable=True),
        sa.Column("member_queries", LargeText(), nullable=True, comment="JSON member queries"),
        sa.Column("heat_score", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("unique_users", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("search_count_7d", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("search_count_8_30d", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("qualified", sa.SmallInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("final_rank", sa.SmallInteger(), nullable=True),
        sa.Column("rewrite_source", sa.String(length=16), nullable=True, comment="passthrough/llm/fallback"),
        sa.Column("llm_sample", LargeText(), nullable=True, comment="Truncated LLM I/O sample"),
        sa.Column("computed_at", sa.DateTime(), nullable=False),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )


def _create_indexes(table_name: str, indexes: dict[str, list[str]]) -> None:
    connection = op.get_bind()
    for index_name, columns in indexes.items():
        if not index_exists(connection, table_name, index_name):
            op.create_index(index_name, table_name, columns, unique=False)


def upgrade() -> None:
    connection = op.get_bind()
    if not table_exists(connection, _SNAPSHOT_TABLE):
        _create_snapshot_table()
    if not table_exists(connection, _BATCH_RUN_TABLE):
        _create_batch_run_table()
    if not table_exists(connection, _CANDIDATE_TABLE):
        _create_candidate_table()
    _create_indexes(_SNAPSHOT_TABLE, _SNAPSHOT_INDEXES)
    _create_indexes(_BATCH_RUN_TABLE, _BATCH_RUN_INDEXES)
    _create_indexes(_CANDIDATE_TABLE, _CANDIDATE_INDEXES)


def _drop_feature_table(table_name: str, indexes: dict[str, list[str]]) -> None:
    connection = op.get_bind()
    if not table_exists(connection, table_name):
        return
    for index_name in reversed(list(indexes)):
        if index_exists(connection, table_name, index_name):
            op.drop_index(index_name, table_name=table_name)
    op.drop_table(table_name)


def downgrade() -> None:
    _drop_feature_table(_CANDIDATE_TABLE, _CANDIDATE_INDEXES)
    _drop_feature_table(_BATCH_RUN_TABLE, _BATCH_RUN_INDEXES)
    _drop_feature_table(_SNAPSHOT_TABLE, _SNAPSHOT_INDEXES)
