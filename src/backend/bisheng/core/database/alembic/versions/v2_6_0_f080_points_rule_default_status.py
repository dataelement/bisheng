"""按产品约定同步 point_rule 默认启停。

Revision ID: f080_points_rule_default_status
Revises: f079_points_seed_g1g7_m1m8

默认 enabled：G1–G4、R1–R3、M1/M4/M6。
种子中其余编码（G5–G7、M2/M3/M5/M7/M8）设为 disabled。
不改名称/分值等运营字段。
"""

from alembic import op
import sqlalchemy as sa

from bisheng.points.domain.constants.seed_rules import SEED_RULES

revision = "f080_points_rule_default_status"
down_revision = "f079_points_seed_g1g7_m1m8"
branch_labels = None
depends_on = None


def table_exists(bind, name: str) -> bool:
    """跨数据库检查表是否已存在。"""
    return name in sa.inspect(bind).get_table_names()


def upgrade():
    """将种子规则的 status 写回各租户已有行。"""
    bind = op.get_bind()
    if not table_exists(bind, "point_rule"):
        return
    for rule in SEED_RULES:
        bind.execute(
            sa.text(
                "UPDATE point_rule SET status = :status "
                "WHERE rule_code = :code"
            ),
            {"status": rule["status"], "code": rule["rule_code"]},
        )


def downgrade():
    """不回滚启停（运营可能已再次调整）。"""
    pass
