"""Add department.sync_parent_external_id for deferred SG parent linking.

Revision ID: f047_department_sync_parent_external_id
Revises: f046_review_tag_schema
Create Date: 2026-06-18
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import column_exists, index_exists

revision: str = "f047_department_sync_parent_external_id"
down_revision: Union[str, Sequence[str], None] = "f046_review_tag_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    if not column_exists(conn, "department", "sync_parent_external_id"):
        op.add_column(
            "department",
            sa.Column(
                "sync_parent_external_id",
                sa.String(128),
                nullable=True,
                comment="SG sync: pending parent external_id before parent row exists",
            ),
        )
    if not index_exists(conn, "department", "idx_department_sync_parent_external_id"):
        op.create_index(
            "idx_department_sync_parent_external_id",
            "department",
            ["source", "sync_parent_external_id"],
        )


def downgrade() -> None:
    conn = op.get_bind()
    if index_exists(conn, "department", "idx_department_sync_parent_external_id"):
        op.drop_index(
            "idx_department_sync_parent_external_id",
            table_name="department",
        )
    if column_exists(conn, "department", "sync_parent_external_id"):
        op.drop_column("department", "sync_parent_external_id")
