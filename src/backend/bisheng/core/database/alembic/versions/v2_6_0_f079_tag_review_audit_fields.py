"""F079: add tag review audit-trail fields.

Records who reviewed a tag and when. ``review_tag`` already had ``review_time``
but never stored the reviewer; ``tag`` kept neither, so once an approved tag was
moved from ``review_tag`` into ``tag`` the audit trail was lost entirely.

Pure additive migration: three nullable columns, no data backfill, no changes to
existing columns. Rolling back only drops the columns, so pre-existing behaviour
is unaffected.

Revision ID: f079_tag_review_audit_fields
Revises: f078_knowledge_parse_priority
Create Date: 2026-08-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f079_tag_review_audit_fields"
down_revision: str | Sequence[str] | None = "f078_knowledge_parse_priority"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, column, type, comment)
_COLUMNS: tuple[tuple[str, str, sa.types.TypeEngine, str], ...] = (
    (
        "review_tag",
        "reviewer_id",
        sa.Integer(),
        "User ID of the reviewer; written on both approve and reject",
    ),
    (
        "tag",
        "reviewer_id",
        sa.Integer(),
        "User ID of the reviewer, carried over when an approved tag is moved here",
    ),
    (
        "tag",
        "review_time",
        sa.DateTime(),
        "Review timestamp, carried over when an approved tag is moved here",
    ),
)


def _has_column(bind, table: str, column: str) -> bool:
    inspector = sa.inspect(bind)
    return any(item["name"] == column for item in inspector.get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    for table, column, column_type, comment in _COLUMNS:
        if not _has_column(bind, table, column):
            op.add_column(
                table,
                sa.Column(column, column_type, nullable=True, comment=comment),
            )


def downgrade() -> None:
    bind = op.get_bind()
    for table, column, _column_type, _comment in reversed(_COLUMNS):
        if _has_column(bind, table, column):
            op.drop_column(table, column)
