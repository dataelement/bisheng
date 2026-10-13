"""文档纠错单, 待处理占位, 积分名额, 以及 G8 规则种子.

Revision ID: f110_knowledge_file_correction
Revises: f109_background_jobs
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT, table_exists
from bisheng.points.domain.constants.seed_rules import SEED_RULES
from bisheng.points.domain.models import PointRule

revision: str = "f110_knowledge_file_correction"
down_revision: str | Sequence[str] | None = "f109_background_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """建三张纠错表, 并为已有租户补 G8."""
    connection = op.get_bind()
    if not table_exists(connection, "knowledge_file_correction"):
        op.create_table(
            "knowledge_file_correction",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False, autoincrement=True, comment="主键"),
            sa.Column("tenant_id", sa.Integer(), nullable=False, server_default=sa.text("1"), comment="租户ID"),
            sa.Column("file_id", sa.Integer(), nullable=False, comment="知识库文件ID"),
            sa.Column("knowledge_id", sa.Integer(), nullable=False, comment="知识库ID"),
            sa.Column("applicant_user_id", sa.Integer(), nullable=False, comment="反馈人用户ID"),
            sa.Column("applicant_user_name", sa.String(255), nullable=False, server_default=sa.text("''"), comment="反馈人姓名快照"),
            sa.Column("uploader_user_id", sa.Integer(), nullable=False, comment="提交时冻结的上传人用户ID"),
            sa.Column("uploader_user_name", sa.String(255), nullable=False, server_default=sa.text("''"), comment="上传人姓名快照"),
            sa.Column("file_name", sa.String(255), nullable=False, server_default=sa.text("''"), comment="文档名快照"),
            sa.Column("content", sa.String(500), nullable=False, comment="纠错说明, 最多500字"),
            sa.Column("status", sa.String(16), nullable=False, comment="状态: pending/approved/rejected/withdrawn/cancelled"),
            sa.Column("approval_instance_id", sa.Integer(), nullable=True, comment="审批实例ID"),
            sa.Column("create_time", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="创建时间"),
            sa.Column("update_time", sa.DateTime(), nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT, comment="更新时间"),
            mysql_charset="utf8mb4",
            mysql_collate="utf8mb4_unicode_ci",
        )
        op.create_index("idx_kfc_file_status", "knowledge_file_correction", ["file_id", "status"])
        op.create_index("idx_kfc_tenant_applicant", "knowledge_file_correction", ["tenant_id", "applicant_user_id"])
    if not table_exists(connection, "knowledge_file_correction_open"):
        op.create_table(
            "knowledge_file_correction_open",
            sa.Column("tenant_id", sa.Integer(), primary_key=True, nullable=False, comment="租户ID"),
            sa.Column("file_id", sa.Integer(), primary_key=True, nullable=False, comment="知识库文件ID"),
            sa.Column("applicant_user_id", sa.Integer(), primary_key=True, nullable=False, comment="反馈人用户ID"),
            sa.Column("correction_id", sa.Integer(), nullable=False, comment="待处理纠错单ID"),
            mysql_charset="utf8mb4",
            mysql_collate="utf8mb4_unicode_ci",
        )
    if not table_exists(connection, "knowledge_file_correction_award"):
        op.create_table(
            "knowledge_file_correction_award",
            sa.Column("tenant_id", sa.Integer(), primary_key=True, nullable=False, comment="租户ID"),
            sa.Column("file_id", sa.Integer(), primary_key=True, nullable=False, comment="知识库文件ID"),
            sa.Column("applicant_user_id", sa.Integer(), primary_key=True, nullable=False, comment="反馈人用户ID"),
            sa.Column("correction_id", sa.Integer(), nullable=False, comment="占用名额的纠错单ID"),
            sa.Column("award_state", sa.String(16), nullable=False, comment="名额结果: reserved/awarded/skipped"),
            mysql_charset="utf8mb4",
            mysql_collate="utf8mb4_unicode_ci",
        )
    _seed_g8(connection)


def _seed_g8(connection) -> None:
    if not table_exists(connection, "point_rule"):
        return
    rule = next((item for item in SEED_RULES if item["rule_code"] == "G8"), None)
    if rule is None:
        return
    rows = connection.execute(sa.text("SELECT DISTINCT tenant_id FROM point_rule")).fetchall()
    tenant_ids = sorted({int(row[0]) for row in rows}) or [1]
    for tenant_id in tenant_ids:
        exists = connection.execute(
            sa.text("SELECT 1 FROM point_rule WHERE tenant_id = :tid AND rule_code = 'G8' LIMIT 1"),
            {"tid": tenant_id},
        ).first()
        if exists:
            continue
        connection.execute(
            sa.insert(PointRule.__table__),
            [{"tenant_id": tenant_id, "remark": None, **rule}],
        )


def downgrade() -> None:
    """不删除已产生的纠错单和 G8 流水."""
    pass
