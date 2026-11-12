"""Add private move subject lookup facts without deriving historical identities."""

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists, index_exists, table_exists

revision = "f118_move_actor_subject"
down_revision = "f118_finalize_retry"
branch_labels = None
depends_on = None

TABLES = ("knowledge_processing_job", "knowledge_processing_retry_receipt")
RETRY_INDEX = "ix_kpr_job_subject"
INDEX_COLUMNS = ["tenant_id", "job_id", "actor_subject_id", "actor_subject_type", "accepted_job_revision", "id"]


def upgrade():
    for table in TABLES:
        if not table_exists(table):
            continue
        for column in (
            sa.Column("actor_subject_type", sa.String(32), nullable=True),
            sa.Column("actor_subject_id", sa.BigInteger(), nullable=True),
        ):
            if not column_exists(table, column.name):
                op.add_column(table, column)
    if table_exists(TABLES[1]) and not index_exists(TABLES[1], RETRY_INDEX):
        op.create_index(RETRY_INDEX, TABLES[1], INDEX_COLUMNS, unique=False)


def downgrade():
    raise RuntimeError("F118 rollback requires the maintenance-window consistent backup")
