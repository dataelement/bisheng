"""Retain bounded configured-word snapshots; legacy events stay unknown (NULL)."""

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists, table_exists
from bisheng.core.database.dialect_helpers import JsonType

revision = "f111_matched_words"
down_revision = "f111_dsh_content_safety"
branch_labels = None
depends_on = None


def upgrade():
    if table_exists("dsh_content_safety_event") and not column_exists("dsh_content_safety_event", "matched_words"):
        op.add_column("dsh_content_safety_event", sa.Column("matched_words", JsonType(), nullable=True))


def downgrade():
    raise RuntimeError(
        "Matched-word evidence must be retained; schema contraction requires a separate operator procedure"
    )
