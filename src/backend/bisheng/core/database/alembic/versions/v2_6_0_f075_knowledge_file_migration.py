"""Add persistent control-plane tables for cross-space file migration.

Revision ID: f075_knowledge_file_migration
Revises: f074_add_qa_question_file_name
Create Date: 2026-07-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import (
    UPDATE_TIME_SERVER_DEFAULT,
    JsonType,
    index_exists,
    table_exists,
)

revision: str = "f075_knowledge_file_migration"
down_revision: str | Sequence[str] | None = "f074_add_qa_question_file_name"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BATCH = "knowledge_migration_batch"
_UNIT = "knowledge_migration_unit"
_FILE = "knowledge_migration_file"
_ATTEMPT = "knowledge_migration_attempt"

_INDEXES: dict[str, dict[str, list[str]]] = {
    _BATCH: {
        "ix_kmb_deleted_created": ["deleted_at", "create_time", "id"],
        "ix_kmb_status_created": ["status", "create_time", "id"],
        "ix_kmb_status_queued": ["status", "queued_at", "id"],
    },
    _UNIT: {
        "ix_kmu_batch_status": ["batch_id", "status", "id"],
        "ix_kmu_batch_round_status": ["batch_id", "current_round_no", "status", "id"],
    },
    _FILE: {
        "ix_kmf_unit_version": ["unit_id", "source_version_no", "id"],
    },
    _ATTEMPT: {
        "ix_kma_batch_round": ["batch_id", "round_no", "id"],
    },
}


def _pk_type() -> sa.types.TypeEngine:
    return sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def _audit_columns() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column(
            "create_time",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "update_time",
            sa.DateTime(),
            nullable=False,
            server_default=UPDATE_TIME_SERVER_DEFAULT,
        ),
    )


def _table_options() -> dict[str, str]:
    return {
        "mysql_charset": "utf8mb4",
        "mysql_collate": "utf8mb4_unicode_ci",
    }


def _create_batch() -> None:
    op.create_table(
        _BATCH,
        sa.Column("id", _pk_type(), primary_key=True, autoincrement=True),
        sa.Column("batch_no", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("operator_id", sa.BigInteger(), nullable=False),
        sa.Column("operator_name", sa.String(128), nullable=False),
        sa.Column("source_selection_snapshot", JsonType(), nullable=False),
        sa.Column("source_spaces_snapshot", JsonType(), nullable=False),
        sa.Column("target_space_id", sa.BigInteger(), nullable=False),
        sa.Column("target_space_name", sa.String(200), nullable=False),
        sa.Column("target_space_level", sa.String(32), nullable=True),
        sa.Column("target_folder_id", sa.BigInteger(), nullable=True),
        sa.Column("target_folder_name", sa.String(200), nullable=True),
        sa.Column("target_path_snapshot", sa.String(1024), nullable=False, server_default=sa.text("'/'")),
        sa.Column("conflict_strategy", sa.String(16), nullable=False, server_default=sa.text("'skip'")),
        sa.Column("preserve_structure", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default=sa.text("'preflight_queued'"),
        ),
        sa.Column(
            "current_stage",
            sa.String(32),
            nullable=False,
            server_default=sa.text("'preflight_queued'"),
        ),
        sa.Column("round_no", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("scanned_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("total_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("executable_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("completed_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("succeeded_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("unprocessed_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("overwrite_target_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("preflight_task_id", sa.String(64), nullable=True),
        sa.Column("execution_task_id", sa.String(64), nullable=True),
        sa.Column("last_error_code", sa.String(64), nullable=True),
        sa.Column("last_error_summary", sa.Text(), nullable=True),
        sa.Column("confirmed_by", sa.BigInteger(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("abandoned_by", sa.BigInteger(), nullable=True),
        sa.Column("abandoned_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_by", sa.BigInteger(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("queued_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        *_audit_columns(),
        sa.UniqueConstraint("batch_no", name="uk_knowledge_migration_batch_no"),
        sa.UniqueConstraint("operator_id", "request_id", name="uk_knowledge_migration_request"),
        **_table_options(),
    )


def _create_unit() -> None:
    op.create_table(
        _UNIT,
        sa.Column("id", _pk_type(), primary_key=True, autoincrement=True),
        sa.Column("batch_id", sa.BigInteger(), nullable=False),
        sa.Column("unit_key", sa.String(96), nullable=False),
        sa.Column("unit_type", sa.String(24), nullable=False, server_default=sa.text("'file'")),
        sa.Column("source_document_id", sa.BigInteger(), nullable=True),
        sa.Column("source_space_id", sa.BigInteger(), nullable=False),
        sa.Column("source_space_name", sa.String(200), nullable=False),
        sa.Column("source_space_level", sa.String(32), nullable=True),
        sa.Column("source_parent_folder_id", sa.BigInteger(), nullable=True),
        sa.Column("source_path_snapshot", sa.String(1024), nullable=False, server_default=sa.text("'/'")),
        sa.Column("planned_target_folder_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "planned_target_path_snapshot",
            sa.String(1024),
            nullable=False,
            server_default=sa.text("'/'"),
        ),
        sa.Column("status", sa.String(24), nullable=False, server_default=sa.text("'planned'")),
        sa.Column("reason_code", sa.String(64), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("checkpoint", sa.String(32), nullable=False, server_default=sa.text("'planned'")),
        sa.Column("target_document_id", sa.BigInteger(), nullable=True),
        sa.Column("overwrite_unit_key", sa.String(96), nullable=True),
        sa.Column("overwrite_snapshot", JsonType(), nullable=True),
        sa.Column("folder_mapping_snapshot", JsonType(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("current_round_no", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        *_audit_columns(),
        sa.UniqueConstraint("batch_id", "unit_key", name="uk_knowledge_migration_unit_key"),
        **_table_options(),
    )


def _create_file() -> None:
    op.create_table(
        _FILE,
        sa.Column("id", _pk_type(), primary_key=True, autoincrement=True),
        sa.Column("batch_id", sa.BigInteger(), nullable=False),
        sa.Column("unit_id", sa.BigInteger(), nullable=False),
        sa.Column("source_file_id", sa.BigInteger(), nullable=False),
        sa.Column("source_document_id", sa.BigInteger(), nullable=True),
        sa.Column("source_version_id", sa.BigInteger(), nullable=True),
        sa.Column("source_version_no", sa.Integer(), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("source_space_id", sa.BigInteger(), nullable=False),
        sa.Column("source_space_name", sa.String(200), nullable=False),
        sa.Column("source_folder_id", sa.BigInteger(), nullable=True),
        sa.Column("source_path_snapshot", sa.String(1024), nullable=False, server_default=sa.text("'/'")),
        sa.Column("source_file_name", sa.String(200), nullable=False),
        sa.Column("source_metadata_snapshot", JsonType(), nullable=True),
        sa.Column("source_resource_manifest", JsonType(), nullable=True),
        sa.Column("target_file_id", sa.BigInteger(), nullable=True),
        sa.Column("target_space_id", sa.BigInteger(), nullable=False),
        sa.Column("target_space_name", sa.String(200), nullable=False),
        sa.Column("target_folder_id", sa.BigInteger(), nullable=True),
        sa.Column("target_path_snapshot", sa.String(1024), nullable=False, server_default=sa.text("'/'")),
        sa.Column("target_file_name", sa.String(200), nullable=False),
        sa.Column("target_resource_manifest", JsonType(), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default=sa.text("'planned'")),
        sa.Column("checkpoint", sa.String(32), nullable=False, server_default=sa.text("'planned'")),
        sa.Column("reason_code", sa.String(64), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        *_audit_columns(),
        sa.UniqueConstraint("batch_id", "source_file_id", name="uk_knowledge_migration_source_file"),
        **_table_options(),
    )


def _create_attempt() -> None:
    op.create_table(
        _ATTEMPT,
        sa.Column("id", _pk_type(), primary_key=True, autoincrement=True),
        sa.Column("batch_id", sa.BigInteger(), nullable=False),
        sa.Column("unit_id", sa.BigInteger(), nullable=False),
        sa.Column("round_no", sa.Integer(), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("worker_task_id", sa.String(64), nullable=True),
        sa.Column("execution_token", sa.String(64), nullable=False),
        sa.Column("start_checkpoint", sa.String(32), nullable=False, server_default=sa.text("'planned'")),
        sa.Column("end_checkpoint", sa.String(32), nullable=True),
        sa.Column("result", sa.String(24), nullable=False, server_default=sa.text("'running'")),
        sa.Column("reason_code", sa.String(64), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        *_audit_columns(),
        sa.UniqueConstraint("unit_id", "attempt_no", name="uk_knowledge_migration_attempt_no"),
        **_table_options(),
    )


def _create_indexes(table_name: str) -> None:
    connection = op.get_bind()
    for index_name, columns in _INDEXES[table_name].items():
        if not index_exists(connection, table_name, index_name):
            op.create_index(index_name, table_name, columns, unique=False)


def upgrade() -> None:
    connection = op.get_bind()
    creators = (
        (_BATCH, _create_batch),
        (_UNIT, _create_unit),
        (_FILE, _create_file),
        (_ATTEMPT, _create_attempt),
    )
    for table_name, creator in creators:
        if not table_exists(connection, table_name):
            creator()
        _create_indexes(table_name)


def downgrade() -> None:
    connection = op.get_bind()
    for table_name in (_ATTEMPT, _FILE, _UNIT, _BATCH):
        if not table_exists(connection, table_name):
            continue
        for index_name in reversed(_INDEXES[table_name]):
            if index_exists(connection, table_name, index_name):
                op.drop_index(index_name, table_name=table_name)
        op.drop_table(table_name)
