"""F025 dataset catalog and transient task ownership; DDL only."""

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists, index_exists

revision = "v310_f025_dataset_catalog"
down_revision = "v310_f025_merge_release_heads"
branch_labels = None
depends_on = None


def upgrade():
    for column in [
        sa.Column("data_type", sa.String(32), nullable=False, server_default="legacy"),
        sa.Column("source_type", sa.String(16), nullable=False, server_default="local"),
        sa.Column("version_id", sa.String(64), nullable=True),
        sa.Column("source_dataset_id", sa.String(64), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
    ]:
        if not column_exists("presettrain", column.name):
            op.add_column("presettrain", column)
    if not column_exists("finetune", "transient_upload_id"):
        op.add_column("finetune", sa.Column("transient_upload_id", sa.String(64), nullable=True))
    for table, column, unique in [
        ("presettrain", "data_type", False),
        ("presettrain", "is_deleted", False),
        ("presettrain", "version_id", True),
        ("finetune", "transient_upload_id", True),
    ]:
        name = f"ix_{table}_{column}"
        if not index_exists(table, name):
            op.create_index(name, table, [column], unique=unique)


def downgrade():
    for table, column in [
        ("finetune", "transient_upload_id"),
        ("presettrain", "version_id"),
        ("presettrain", "is_deleted"),
        ("presettrain", "data_type"),
    ]:
        name = f"ix_{table}_{column}"
        if index_exists(table, name):
            op.drop_index(name, table_name=table)
    for table, columns in [
        ("finetune", ["transient_upload_id"]),
        ("presettrain", ["data_type", "source_type", "version_id", "source_dataset_id", "is_deleted"]),
    ]:
        for column in columns:
            if column_exists(table, column):
                op.drop_column(table, column)
