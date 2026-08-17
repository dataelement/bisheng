"""F048: add the single-slot visible source projection index.

The table is rebuildable control-plane state. This revision is DDL-only; the
formal F048 migration script owns all contribution backfill and verification.

Revision ID: f048_visible_source_projection
Revises: linsight_pending_files
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import table_exists

revision: str = "f048_visible_source_projection"
down_revision: str | Sequence[str] | None = "linsight_pending_files"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "permission_visible_source_projection"


def upgrade() -> None:
    if table_exists(_TABLE):
        return

    op.create_table(
        _TABLE,
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.String(64), nullable=False),
        sa.Column("visibility_class", sa.String(64), nullable=False),
        sa.Column("projected_subject", sa.String(256), nullable=False),
        sa.Column("source_kind", sa.String(64), nullable=False),
        sa.Column("source_owner_key", sa.String(256), nullable=False),
        sa.Column("source_locator", sa.String(256), nullable=False),
        sa.Column("source_fingerprint", sa.CHAR(64), nullable=False),
        sa.Column("contribution_fingerprint", sa.CHAR(64), nullable=False),
        sa.Column("model_key", sa.String(64), nullable=True),
        sa.Column("source_version", sa.BigInteger(), nullable=False),
        sa.Column("tuple_fingerprint", sa.CHAR(64), nullable=False),
        sa.Column(
            "state",
            sa.String(64),
            nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
        sa.Column("operation_id", sa.BigInteger(), nullable=True),
        sa.Column("migration_item_id", sa.BigInteger(), nullable=True),
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
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["permission_projection_operation.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["migration_item_id"],
            ["permission_migration_item.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "resource_type",
            "resource_id",
            "visibility_class",
            "projected_subject",
            "contribution_fingerprint",
            name="uq_perm_visible_source_contribution",
        ),
    )
    op.create_index("ix_permission_visible_source_projection_tenant_id", _TABLE, ["tenant_id"])
    op.create_index(
        "ix_perm_visible_resource_subject",
        _TABLE,
        [
            "tenant_id",
            "resource_type",
            "resource_id",
            "visibility_class",
            "projected_subject",
            "state",
        ],
    )
    op.create_index(
        "ix_perm_visible_model_state",
        _TABLE,
        ["model_key", "state", "tenant_id", "id"],
    )
    op.create_index(
        "ix_perm_visible_source_owner",
        _TABLE,
        ["tenant_id", "source_kind", "source_owner_key", "state", "id"],
    )
    op.create_index(
        "ix_perm_visible_operation",
        _TABLE,
        ["tenant_id", "operation_id", "state", "id"],
    )
    op.create_index(
        "ix_perm_visible_migration_item",
        _TABLE,
        ["migration_item_id", "state", "id"],
    )


def downgrade() -> None:
    """Drop the table before any formal F048 data-migration run is created.

    After a formal run starts, the release runbook forbids application-level
    downgrade and requires forward repair. The DDL revision deliberately does
    not inspect business rows to enforce that operational precondition.
    """

    if table_exists(_TABLE):
        op.drop_table(_TABLE)
