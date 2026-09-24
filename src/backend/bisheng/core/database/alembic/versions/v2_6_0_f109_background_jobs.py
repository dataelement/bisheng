"""持久化知识库发布及清理意图, 不扫描或补删历史数据。"""

import sqlalchemy as sa
from alembic import op
from bisheng.core.database.dialect_helpers import JsonType

revision = "f109_background_jobs"
down_revision = "f108_background_budgets"
branch_labels = None
depends_on = None


def upgrade():
    if not sa.inspect(op.get_bind()).has_table("knowledge_background_job"):
        op.create_table(
            "knowledge_background_job",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("kind", sa.String(32), nullable=False),
            sa.Column("parent_id", sa.String(64), nullable=True),
            sa.Column("payload", JsonType(), nullable=False),
            sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("lease_owner", sa.String(64), nullable=True),
            sa.Column("lease_until", sa.DateTime(), nullable=True),
            sa.Column("next_retry_at", sa.DateTime(), nullable=True),
            sa.Column("last_error", sa.String(1000), nullable=True),
            sa.Column("create_time", sa.DateTime(), nullable=False),
            sa.Column("update_time", sa.DateTime(), nullable=False),
        )
    indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("knowledge_background_job")}
    for name, columns in (
        ("ix_kbj_due", ["status", "next_retry_at", "lease_until"]),
        ("ix_knowledge_background_job_tenant_id", ["tenant_id"]),
        ("ix_knowledge_background_job_parent_id", ["parent_id"]),
    ):
        if name not in indexes:
            op.create_index(name, "knowledge_background_job", columns)


def downgrade():
    op.drop_table("knowledge_background_job")
