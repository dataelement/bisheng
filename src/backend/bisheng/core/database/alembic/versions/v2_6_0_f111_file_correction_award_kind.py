"""纠错发分改为按条记录, 并取消 G8 的全局每日上限.

Revision ID: f111_file_correction_award_kind
Revises: f110_knowledge_file_correction
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import table_exists

revision: str = "f111_file_correction_award_kind"
down_revision: str | Sequence[str] | None = "f110_knowledge_file_correction"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """重建名额表. 旧的一人一文档一行无法表达多次采纳并更新."""
    connection = op.get_bind()
    if table_exists(connection, "knowledge_file_correction_award"):
        op.drop_table("knowledge_file_correction_award")
    op.create_table(
        "knowledge_file_correction_award",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False, autoincrement=True, comment="主键"),
        sa.Column("tenant_id", sa.Integer(), nullable=False, server_default=sa.text("1"), comment="租户ID"),
        sa.Column("file_id", sa.Integer(), nullable=False, comment="被纠错的知识库文件ID"),
        sa.Column("applicant_user_id", sa.Integer(), nullable=False, comment="反馈人用户ID"),
        sa.Column("correction_id", sa.Integer(), nullable=False, comment="纠错单ID, 一条纠错只发一次"),
        sa.Column("award_kind", sa.String(16), nullable=False, comment="发分类型: adopt/update"),
        sa.Column("award_state", sa.String(16), nullable=False, comment="名额结果: reserved/awarded/skipped"),
        sa.Column(
            "create_time",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            comment="创建时间",
        ),
        sa.UniqueConstraint("correction_id", name="uk_kfca_correction"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "idx_kfca_adopt_day",
        "knowledge_file_correction_award",
        ["tenant_id", "file_id", "applicant_user_id", "award_kind", "create_time"],
    )
    if table_exists(connection, "point_rule"):
        connection.execute(
            sa.text(
                "UPDATE point_rule SET daily_cap = NULL, "
                "score_expr = :expr WHERE rule_code = 'G8'"
            ),
            {"expr": '{"mode": "fixed", "score": 1}'},
        )


def downgrade() -> None:
    """不恢复旧的一人一文档名额表."""
    pass
