"""F045: add is_hidden flag to department knowledge space bindings.

Soft-hide a department knowledge space from the management list without
deleting the underlying knowledge space, files or member permissions.

Revision ID: f045_dks_is_hidden
Revises: f035_linsight_skills
Create Date: 2026-06-26
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import column_exists

revision: str = "f045_dks_is_hidden"
down_revision: Union[str, Sequence[str], None] = "f035_linsight_skills"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    if not column_exists(conn, "department_knowledge_space", "is_hidden"):
        op.add_column(
            "department_knowledge_space",
            sa.Column(
                "is_hidden",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
                comment="Hidden from the department knowledge space management list "
                "(knowledge space, files and member permissions are all preserved)",
            ),
        )


def downgrade() -> None:
    conn = op.get_bind()
    if column_exists(conn, "department_knowledge_space", "is_hidden"):
        op.drop_column("department_knowledge_space", "is_hidden")
