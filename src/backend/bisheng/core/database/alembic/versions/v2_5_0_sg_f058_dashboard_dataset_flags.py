"""Add dashboard_dataset visibility and grouping flags (F058).

Revision ID: f058_dashboard_dataset_flags
Revises: f105_portal_catalog_external_id
Create Date: 2026-09-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import column_exists, table_exists

revision: str = "f058_dashboard_dataset_flags"
down_revision: str | Sequence[str] | None = "f105_portal_catalog_external_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "dashboard_dataset"
_IS_VISIBLE = "is_visible"
_DATASET_GROUP = "dataset_group"


def upgrade() -> None:
    connection = op.get_bind()
    if not table_exists(connection, _TABLE):
        return
    missing_visible = not column_exists(connection, _TABLE, _IS_VISIBLE)
    missing_group = not column_exists(connection, _TABLE, _DATASET_GROUP)
    if not missing_visible and not missing_group:
        return
    if connection.dialect.name == "sqlite":
        with op.batch_alter_table(_TABLE) as batch_op:
            if missing_visible:
                batch_op.add_column(
                    sa.Column(
                        _IS_VISIBLE,
                        sa.Boolean(),
                        nullable=False,
                        server_default=sa.true(),
                        comment="Whether this dataset is selectable in the dashboard UI",
                    )
                )
            if missing_group:
                batch_op.add_column(
                    sa.Column(
                        _DATASET_GROUP,
                        sa.String(64),
                        nullable=True,
                        comment="Optional grouping key for the dataset picker UI",
                    )
                )
        return
    if missing_visible:
        op.add_column(
            _TABLE,
            sa.Column(
                _IS_VISIBLE,
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
                comment="Whether this dataset is selectable in the dashboard UI",
            ),
        )
    if missing_group:
        op.add_column(
            _TABLE,
            sa.Column(
                _DATASET_GROUP,
                sa.String(64),
                nullable=True,
                comment="Optional grouping key for the dataset picker UI",
            ),
        )


def downgrade() -> None:
    connection = op.get_bind()
    if not table_exists(connection, _TABLE):
        return
    # Pure additive columns with no dependent data — dropping them is lossless: the
    # dataset picker just falls back to "all visible, no grouping" (the pre-F058 behavior).
    if connection.dialect.name == "sqlite":
        with op.batch_alter_table(_TABLE) as batch_op:
            if column_exists(connection, _TABLE, _DATASET_GROUP):
                batch_op.drop_column(_DATASET_GROUP)
            if column_exists(connection, _TABLE, _IS_VISIBLE):
                batch_op.drop_column(_IS_VISIBLE)
        return
    if column_exists(connection, _TABLE, _DATASET_GROUP):
        op.drop_column(_TABLE, _DATASET_GROUP)
    if column_exists(connection, _TABLE, _IS_VISIBLE):
        op.drop_column(_TABLE, _IS_VISIBLE)
