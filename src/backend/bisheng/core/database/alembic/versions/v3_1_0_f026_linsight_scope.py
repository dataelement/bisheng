"""F026: persist the fixed tag scope frozen on a task round.

The task must search exactly what the user pinned when the task was created.
A NULL column means "this round never recorded a tag scope" (pre-F026 rows);
an empty object means the client explicitly declared an empty selection.
"""

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists
from bisheng.core.database.dialect_helpers import JsonType

revision = "f026_linsight_scope"
down_revision = "f026_provider_control"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not column_exists("linsight_session_version", "knowledge_space_tag_filters"):
        op.add_column(
            "linsight_session_version",
            sa.Column("knowledge_space_tag_filters", JsonType, nullable=True),
        )


def downgrade() -> None:
    if column_exists("linsight_session_version", "knowledge_space_tag_filters"):
        op.drop_column("linsight_session_version", "knowledge_space_tag_filters")
