"""Add qa_expert job fields.

Revision ID: f064_add_qa_expert_job_fields
Revises: f063_knowledge_file_pdf_artifact
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import column_exists, table_exists

revision: str = "f064_add_qa_expert_job_fields"
down_revision: str | Sequence[str] | None = "f063_knowledge_file_pdf_artifact"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "qa_expert"
_COLUMNS = (
    ("position", "Expert position"),
    ("job_family", "Expert job family"),
    ("job_category", "Expert job category"),
)


def upgrade() -> None:
    connection = op.get_bind()
    if not table_exists(connection, _TABLE):
        return

    for column_name, comment in _COLUMNS:
        if column_exists(connection, _TABLE, column_name):
            continue
        op.add_column(
            _TABLE,
            sa.Column(
                column_name,
                sa.String(length=255),
                nullable=True,
                comment=comment,
            ),
        )


def downgrade() -> None:
    connection = op.get_bind()
    if not table_exists(connection, _TABLE):
        return

    for column_name, _comment in reversed(_COLUMNS):
        if column_exists(connection, _TABLE, column_name):
            op.drop_column(_TABLE, column_name)
