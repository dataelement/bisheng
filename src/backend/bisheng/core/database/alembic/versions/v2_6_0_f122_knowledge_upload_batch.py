"""Record one upload confirmation so similarity can be repaired after parse commit.

Revision ID: f122_knowledge_upload_batch
Revises: f121_answer_abnormal_prep_failure

Does not alter knowledgefile and does not backfill historical files.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f122_knowledge_upload_batch"
down_revision: str | Sequence[str] | None = "f121_answer_abnormal_prep_failure"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("knowledge_upload_batch"):
        op.create_table(
            "knowledge_upload_batch",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("tenant_id", sa.Integer(), nullable=False, comment="租户编号"),
            sa.Column("knowledge_id", sa.Integer(), nullable=False, comment="知识库编号"),
            sa.Column("batch_key", sa.String(length=36), nullable=False, comment="一次确认上传的批次键"),
            sa.Column("created_by", sa.Integer(), nullable=False, comment="创建该批次的用户编号"),
            sa.Column(
                "revision",
                sa.Integer(),
                nullable=False,
                server_default="0",
                comment="每有一个批次文件解析成功并进入相似收尾就加 1",
            ),
            sa.Column("create_time", sa.DateTime(), nullable=False, comment="创建时间"),
            sa.Column("update_time", sa.DateTime(), nullable=False, comment="更新时间"),
            sa.UniqueConstraint("tenant_id", "batch_key", name="uk_upload_batch_tenant_key"),
        )
    if not inspector.has_table("knowledge_upload_batch_file"):
        op.create_table(
            "knowledge_upload_batch_file",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("tenant_id", sa.Integer(), nullable=False, comment="租户编号"),
            sa.Column("batch_id", sa.Integer(), nullable=False, comment="上传批次编号"),
            sa.Column("file_id", sa.Integer(), nullable=False, comment="知识库文件编号"),
            sa.Column("create_time", sa.DateTime(), nullable=False, comment="加入批次的时间"),
            sa.UniqueConstraint("file_id", name="uk_upload_batch_file"),
        )
    inspector = sa.inspect(op.get_bind())
    batch_indexes = {item["name"] for item in inspector.get_indexes("knowledge_upload_batch")}
    for name, columns in (
        ("ix_knowledge_upload_batch_tenant_id", ["tenant_id"]),
        ("ix_knowledge_upload_batch_knowledge_id", ["knowledge_id"]),
    ):
        if name not in batch_indexes:
            op.create_index(name, "knowledge_upload_batch", columns)
    file_indexes = {item["name"] for item in inspector.get_indexes("knowledge_upload_batch_file")}
    for name, columns in (
        ("ix_knowledge_upload_batch_file_tenant_id", ["tenant_id"]),
        ("ix_knowledge_upload_batch_file_batch_id", ["batch_id"]),
    ):
        if name not in file_indexes:
            op.create_index(name, "knowledge_upload_batch_file", columns)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("knowledge_upload_batch_file"):
        op.drop_table("knowledge_upload_batch_file")
    if inspector.has_table("knowledge_upload_batch"):
        op.drop_table("knowledge_upload_batch")
