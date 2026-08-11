"""F046: add knowledge-space file-change approval persistence.

Revision ID: f046_ks_file_change_approval
Revises: f048_merge_f046_f047_heads
Create Date: 2026-08-10
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists, table_exists
from bisheng.core.database.dialect_helpers import JsonType, index_exists, update_time_server_default

revision: str = "f046_ks_file_change_approval"
down_revision: Union[str, Sequence[str], None] = "f048_merge_f046_f047_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_F046_TABLES = (
    "knowledge_space_file_change_policy",
    "knowledge_space_file_change_setting",
    "knowledge_space_upload_stage",
    "knowledge_space_file_change_request",
    "knowledge_space_file_change_footprint",
    "knowledge_space_file_change_execution_step",
)


def _create_policy_table(conn) -> None:
    table_name = "knowledge_space_file_change_policy"
    if not table_exists(table_name):
        op.create_table(
            table_name,
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("tenant_id", sa.BigInteger(), nullable=False, server_default=sa.text("1")),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column(
                "scope",
                sa.String(length=32),
                nullable=False,
                server_default=sa.text("'per_space'"),
            ),
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
                server_default=update_time_server_default(conn),
            ),
            sa.UniqueConstraint("tenant_id", name="uq_ks_file_change_policy_tenant"),
        )


def _create_setting_table(conn) -> None:
    table_name = "knowledge_space_file_change_setting"
    if not table_exists(table_name):
        op.create_table(
            table_name,
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("tenant_id", sa.BigInteger(), nullable=False, server_default=sa.text("1")),
            sa.Column("space_id", sa.BigInteger(), nullable=False),
            sa.Column(
                "approval_required",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("1"),
            ),
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
                server_default=update_time_server_default(conn),
            ),
            sa.UniqueConstraint(
                "tenant_id",
                "space_id",
                name="uq_ks_file_change_setting_space",
            ),
        )


def _create_upload_stage_table(conn) -> None:
    table_name = "knowledge_space_upload_stage"
    indexes = (
        (
            "idx_ks_upload_stage_cleanup",
            ["tenant_id", "state", "expire_at", "id"],
        ),
        (
            "idx_ks_upload_stage_user",
            ["tenant_id", "uploader_user_id", "state"],
        ),
    )
    if not table_exists(table_name):
        op.create_table(
            table_name,
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("upload_id", sa.String(length=64), nullable=False),
            sa.Column("tenant_id", sa.BigInteger(), nullable=False, server_default=sa.text("1")),
            sa.Column("space_id", sa.BigInteger(), nullable=False),
            sa.Column("uploader_user_id", sa.BigInteger(), nullable=False),
            sa.Column("object_name", sa.String(length=1024), nullable=False),
            sa.Column("file_name", sa.String(length=500), nullable=False),
            sa.Column("file_size", sa.BigInteger(), nullable=False),
            sa.Column("content_hash", sa.String(length=128), nullable=False),
            sa.Column(
                "state",
                sa.String(length=32),
                nullable=False,
                server_default=sa.text("'uploaded'"),
            ),
            sa.Column("expire_at", sa.DateTime(), nullable=False),
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
                server_default=update_time_server_default(conn),
            ),
            sa.UniqueConstraint(
                "tenant_id",
                "upload_id",
                name="uq_ks_upload_stage_tenant_upload",
            ),
        )
        for index_name, columns in indexes:
            op.create_index(index_name, table_name, columns)
        return
    for index_name, columns in indexes:
        if not index_exists(conn, table_name, index_name):
            op.create_index(index_name, table_name, columns)


def _create_request_table(conn) -> None:
    table_name = "knowledge_space_file_change_request"
    indexes = (
        (
            "idx_ks_change_request_space_created",
            ["tenant_id", "space_id", "create_time", "id"],
        ),
        (
            "idx_ks_change_request_executed_file",
            ["tenant_id", "space_id", "executed_resource_id"],
        ),
        (
            "idx_ks_change_request_compensate",
            ["tenant_id", "execution_state", "cleanup_state", "update_time", "id"],
        ),
    )
    if not table_exists(table_name):
        op.create_table(
            table_name,
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("tenant_id", sa.BigInteger(), nullable=False, server_default=sa.text("1")),
            sa.Column("space_id", sa.BigInteger(), nullable=False),
            sa.Column("action", sa.String(length=32), nullable=False),
            sa.Column("resource_type", sa.String(length=32), nullable=False),
            sa.Column("resource_id", sa.BigInteger(), nullable=True),
            sa.Column("applicant_user_id", sa.BigInteger(), nullable=False),
            sa.Column("approval_instance_id", sa.BigInteger(), nullable=True),
            sa.Column("upload_stage_id", sa.BigInteger(), nullable=True),
            sa.Column("file_name", sa.String(length=500), nullable=True),
            sa.Column("file_size", sa.BigInteger(), nullable=True),
            sa.Column("content_hash", sa.String(length=128), nullable=True),
            sa.Column("source_parent_id", sa.BigInteger(), nullable=True),
            sa.Column("target_space_id", sa.BigInteger(), nullable=True),
            sa.Column("target_parent_id", sa.BigInteger(), nullable=True),
            sa.Column("action_snapshot", JsonType(), nullable=False),
            sa.Column("executed_resource_id", sa.BigInteger(), nullable=True),
            sa.Column(
                "execution_state",
                sa.String(length=32),
                nullable=False,
                server_default=sa.text("'not_started'"),
            ),
            sa.Column("execution_token", sa.String(length=64), nullable=True),
            sa.Column("execution_checkpoint", JsonType(), nullable=False),
            sa.Column(
                "cleanup_state",
                sa.String(length=32),
                nullable=False,
                server_default=sa.text("'none'"),
            ),
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
                server_default=update_time_server_default(conn),
            ),
            sa.UniqueConstraint(
                "tenant_id",
                "approval_instance_id",
                name="uq_ks_change_request_instance",
            ),
            sa.UniqueConstraint(
                "tenant_id",
                "upload_stage_id",
                name="uq_ks_change_request_upload",
            ),
        )
        for index_name, columns in indexes:
            op.create_index(index_name, table_name, columns)
        return
    for index_name, columns in indexes:
        if not index_exists(conn, table_name, index_name):
            op.create_index(index_name, table_name, columns)


def _create_footprint_table(conn) -> None:
    table_name = "knowledge_space_file_change_footprint"
    indexes = (
        ("idx_ks_change_fp_request", ["tenant_id", "request_id"], {}),
        (
            "idx_ks_change_fp_resource",
            ["tenant_id", "space_id", "resource_type", "resource_id"],
            {},
        ),
        (
            "idx_ks_change_fp_path",
            ["tenant_id", "space_id", "path_root"],
            {"mysql_length": {"path_root": 512}},
        ),
    )
    if not table_exists(table_name):
        op.create_table(
            table_name,
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("tenant_id", sa.BigInteger(), nullable=False, server_default=sa.text("1")),
            sa.Column("request_id", sa.BigInteger(), nullable=False),
            sa.Column("space_id", sa.BigInteger(), nullable=False),
            sa.Column("resource_type", sa.String(length=32), nullable=False),
            sa.Column("resource_id", sa.BigInteger(), nullable=True),
            sa.Column("path_root", sa.String(length=2048), nullable=True),
            sa.Column("lock_scope", sa.String(length=16), nullable=False),
        )
        for index_name, columns, kwargs in indexes:
            op.create_index(index_name, table_name, columns, **kwargs)
        return
    for index_name, columns, kwargs in indexes:
        if not index_exists(conn, table_name, index_name):
            op.create_index(index_name, table_name, columns, **kwargs)


def _create_execution_step_table(conn) -> None:
    table_name = "knowledge_space_file_change_execution_step"
    index_name = "idx_ks_change_step_retry"
    index_columns = ["tenant_id", "state", "next_retry_at", "id"]
    if not table_exists(table_name):
        op.create_table(
            table_name,
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("tenant_id", sa.BigInteger(), nullable=False, server_default=sa.text("1")),
            sa.Column("request_id", sa.BigInteger(), nullable=False),
            sa.Column("step_code", sa.String(length=64), nullable=False),
            sa.Column("attempt_token", sa.String(length=64), nullable=False),
            sa.Column("idempotency_key", sa.String(length=192), nullable=False),
            sa.Column(
                "state",
                sa.String(length=32),
                nullable=False,
                server_default=sa.text("'pending'"),
            ),
            sa.Column(
                "attempt_count",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column("next_retry_at", sa.DateTime(), nullable=True),
            sa.Column("task_id", sa.String(length=255), nullable=True),
            sa.Column("result_digest", sa.String(length=255), nullable=True),
            sa.Column("error_summary", sa.Text(), nullable=True),
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
                server_default=update_time_server_default(conn),
            ),
            sa.Column("acked_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint(
                "tenant_id",
                "request_id",
                "step_code",
                name="uq_ks_change_step",
            ),
        )
        op.create_index(index_name, table_name, index_columns)
        return
    if not index_exists(conn, table_name, index_name):
        op.create_index(index_name, table_name, index_columns)


def _add_deferred_outbox_columns() -> None:
    table_name = "approval_outbox"
    if not table_exists(table_name):
        return
    if not column_exists(table_name, "execution_token"):
        op.add_column(
            table_name,
            sa.Column("execution_token", sa.String(length=64), nullable=True),
        )
    if not column_exists(table_name, "deferred_deadline"):
        op.add_column(
            table_name,
            sa.Column("deferred_deadline", sa.DateTime(), nullable=True),
        )
    if not column_exists(table_name, "heartbeat_at"):
        op.add_column(
            table_name,
            sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
        )


def upgrade() -> None:
    conn = op.get_bind()
    _create_policy_table(conn)
    _create_setting_table(conn)
    _create_upload_stage_table(conn)
    _create_request_table(conn)
    _create_footprint_table(conn)
    _create_execution_step_table(conn)
    _add_deferred_outbox_columns()


def _assert_no_deferred_outbox_rows() -> None:
    table_name = "approval_outbox"
    if not table_exists(table_name) or not column_exists(table_name, "status"):
        return

    constraint_name = "ck_approval_outbox_f046_no_deferred"
    op.create_check_constraint(
        constraint_name,
        table_name,
        "status <> 'deferred'",
    )
    op.drop_constraint(constraint_name, table_name, type_="check")


def downgrade() -> None:
    _assert_no_deferred_outbox_rows()

    for table_name in reversed(_F046_TABLES):
        if table_exists(table_name):
            op.drop_table(table_name)

    table_name = "approval_outbox"
    if table_exists(table_name):
        for column_name in ("heartbeat_at", "deferred_deadline", "execution_token"):
            if column_exists(table_name, column_name):
                op.drop_column(table_name, column_name)
