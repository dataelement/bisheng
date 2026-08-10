"""Add the per-space portal knowledge discovery switch.

Revision ID: f080_portal_discovery_enabled
Revises: f079_tag_review_audit_fields
Create Date: 2026-08-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f080_portal_discovery_enabled"
down_revision: str | Sequence[str] | None = "f079_tag_review_audit_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_NAME = "knowledge_space_scope"
COLUMN_NAME = "portal_discovery_enabled"


def _has_column(bind, table: str, column: str) -> bool:
    return any(item["name"] == column for item in sa.inspect(bind).get_columns(table))


def _backfill(bind) -> None:
    scope = sa.table(
        TABLE_NAME,
        sa.column("tenant_id", sa.Integer()),
        sa.column("space_id", sa.Integer()),
        sa.column("level", sa.String()),
        sa.column("owner_type", sa.String()),
        sa.column("owner_id", sa.Integer()),
        sa.column(COLUMN_NAME, sa.Boolean()),
    )
    binding = sa.table(
        "department_knowledge_space",
        sa.column("tenant_id", sa.Integer()),
        sa.column("department_id", sa.Integer()),
        sa.column("space_id", sa.Integer()),
    )
    valid_department_binding = sa.exists(
        sa.select(sa.literal(1)).where(
            binding.c.space_id == scope.c.space_id,
            binding.c.tenant_id == scope.c.tenant_id,
            binding.c.department_id == scope.c.owner_id,
        )
    )
    bind.execute(
        sa.update(scope)
        .where(
            sa.or_(
                scope.c.level == "public",
                sa.and_(
                    scope.c.level == "department",
                    scope.c.owner_type == "department",
                    valid_department_binding,
                ),
            )
        )
        .values({COLUMN_NAME: True})
    )


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_column(bind, TABLE_NAME, COLUMN_NAME):
        op.add_column(
            TABLE_NAME,
            sa.Column(
                COLUMN_NAME,
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
                comment="Whether the space participates in portal knowledge discovery",
            ),
        )
    _backfill(bind)


def downgrade() -> None:
    bind = op.get_bind()
    if _has_column(bind, TABLE_NAME, COLUMN_NAME):
        op.drop_column(TABLE_NAME, COLUMN_NAME)
