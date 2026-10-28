"""Add DSH safety projections without deleting or rewriting audit facts.

Whole event tables are owned by model discovery/create_all. This revision only
extends existing tables and is safe after create_all already made the columns.
Application rollback retains this schema; empty-schema contraction is a separate
operator procedure, never a conditional data operation in an Alembic revision.
"""

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import (
    column_exists,
    get_check_constraint,
    index_exists,
    table_exists,
    unique_constraint_exists,
)
from bisheng.core.database.dialect_helpers import PreciseDateTime, is_column_nullable

revision = "f111_dsh_content_safety"
down_revision = "f062_credit_multiplier"
branch_labels = None
depends_on = None


def _columns():
    return {
        "dsh_model_audit_request": (
            sa.Column("record_origin", sa.String(16), nullable=False, server_default="MODEL"),
            sa.Column("model_entered", sa.Boolean(), nullable=True),
            sa.Column("model_started_at", PreciseDateTime(), nullable=True),
            sa.Column("safety_source_id", sa.String(64), nullable=True),
            sa.Column("safety_gateway_request_id", sa.String(36), nullable=True),
            sa.Column("input_safety_state", sa.String(16), nullable=False, server_default="UNREPORTED"),
            sa.Column("output_safety_state", sa.String(16), nullable=False, server_default="UNREPORTED"),
            sa.Column("input_safety_version", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
            sa.Column("output_safety_version", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
            sa.Column("has_sensitive_hit", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("input_sensitive_hit", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("output_sensitive_hit", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("content_safety_state", sa.String(16), nullable=False, server_default="UNREPORTED"),
            sa.Column("content_safety_updated_at", PreciseDateTime(), nullable=True),
            sa.Column("policy_version", sa.BigInteger(), nullable=True),
            sa.Column("builtin_digest", sa.String(64), nullable=True),
            sa.Column("safety_projection_version", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
            sa.Column("group_indexed_sensitive_hit", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        ),
        "dsh_model_audit_conversation": (
            sa.Column("sensitive_hit_count", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
            sa.Column("has_sensitive_hit", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        ),
        "dsh_model_audit_setting": (
            sa.Column("audit_deleted_before", PreciseDateTime(), nullable=True),
            sa.Column("cleanup_before", PreciseDateTime(), nullable=True),
            sa.Column("cleanup_after_started_at", PreciseDateTime(), nullable=True),
            sa.Column("cleanup_after_request_id", sa.String(36), nullable=True),
        ),
        "dsh_audit_tree_state": (
            sa.Column("safety_summary_revision", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
            sa.Column(
                "published_safety_summary_revision", sa.BigInteger(), nullable=False, server_default=sa.text("-1")
            ),
            sa.Column("build_safety_summary_revision", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        ),
        "dsh_audit_tree_node": (
            sa.Column("own_sensitive_hit_count", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
            sa.Column("branch_sensitive_hit_count", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        ),
    }


_INDEXES = (
    (
        "dsh_model_audit_request",
        "ix_dma_request_safety_hit",
        ("tenant_id", "has_sensitive_hit", "started_at", "request_id"),
    ),
    (
        "dsh_model_audit_request",
        "ix_dma_request_safety_state",
        ("tenant_id", "content_safety_state", "started_at", "request_id"),
    ),
    (
        "dsh_model_audit_conversation",
        "ix_dma_conversation_safety",
        ("tenant_id", "has_sensitive_hit", "listed_at", "conversation_key"),
    ),
    (
        "dsh_audit_tree_node",
        "ix_dat_safety",
        ("tenant_id", "generation", "branch_sensitive_hit_count", "listed_at", "conversation_key"),
    ),
)
_MODE_CHECK = (
    "(record_origin = 'MODEL' AND effective_mode IS NOT NULL AND effective_mode IN ('METADATA','CONTENT')) OR "
    "(record_origin = 'EXTERNAL_SAFETY' AND effective_mode IS NULL)"
)


def upgrade():
    for table, columns in _columns().items():
        if table_exists(table):
            for column in columns:
                if not column_exists(table, column.name):
                    op.add_column(table, column)

    request_table = "dsh_model_audit_request"
    if table_exists(request_table):
        for name, size in (
            ("session_id", 128),
            ("effective_mode", 16),
            ("model_result", 16),
            ("response_result", 16),
            ("usage_settlement", 16),
        ):
            if column_exists(request_table, name) and not is_column_nullable(op.get_bind(), request_table, name):
                op.alter_column(
                    request_table, name, existing_type=sa.String(size), existing_nullable=False, nullable=True
                )
        # Replace the old mode-only CHECK even when its name is unchanged.
        existing = get_check_constraint(request_table, "ck_dma_request_mode")
        if existing is not None:
            op.drop_constraint(existing["name"], request_table, type_="check")
        op.create_check_constraint("ck_dma_request_mode", request_table, _MODE_CHECK)
        if get_check_constraint(request_table, "ck_dma_request_origin") is None:
            op.create_check_constraint(
                "ck_dma_request_origin", request_table, "record_origin IN ('MODEL','EXTERNAL_SAFETY')"
            )
        if not unique_constraint_exists(request_table, "uq_dma_safety_request"):
            op.create_unique_constraint(
                "uq_dma_safety_request", request_table, ["safety_source_id", "safety_gateway_request_id"]
            )

    for table, name, columns in _INDEXES:
        if table_exists(table) and not index_exists(table, name):
            op.create_index(name, table, list(columns))


def downgrade():
    raise RuntimeError(
        "F111 audit facts must be retained. Roll back the application with safety disabled; "
        "empty-schema contraction requires a separate verified operator procedure."
    )
