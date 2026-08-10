"""补种积分规则：确保 G1–G7、R1–R3、M1–M8 均在 point_rule 中。

Revision ID: f079_points_seed_g1g7_m1m8
Revises: f078_points_system

仅插入缺失的 (tenant_id, rule_code)；不更新已有行，避免覆盖运营改过的分值/名称。
"""

from alembic import op
import sqlalchemy as sa

from bisheng.points.domain.constants.seed_rules import SEED_COPIES, SEED_RULES
from bisheng.points.domain.models import PointCopy, PointRule

revision = "f079_points_seed_g1g7_m1m8"
down_revision = "f078_points_system"
branch_labels = None
depends_on = None


def table_exists(bind, name: str) -> bool:
    """跨数据库检查表是否已存在。"""
    return name in sa.inspect(bind).get_table_names()


def _tenant_ids(bind) -> list[int]:
    """有规则的租户；若表空则至少补 tenant=1。"""
    rows = bind.execute(sa.text("SELECT DISTINCT tenant_id FROM point_rule")).fetchall()
    ids = sorted({int(r[0]) for r in rows})
    return ids or [1]


def upgrade():
    """按种子补齐缺失规则与文案。"""
    bind = op.get_bind()
    if not table_exists(bind, "point_rule"):
        return

    for tenant_id in _tenant_ids(bind):
        for rule in SEED_RULES:
            code = rule["rule_code"]
            exists = bind.execute(
                sa.text(
                    "SELECT 1 FROM point_rule WHERE tenant_id = :tid AND rule_code = :code LIMIT 1"
                ),
                {"tid": tenant_id, "code": code},
            ).first()
            if exists:
                continue
            bind.execute(
                sa.insert(PointRule.__table__),
                [
                    {
                        "tenant_id": tenant_id,
                        "remark": None,
                        **rule,
                    }
                ],
            )

        if table_exists(bind, "point_copy"):
            for copy in SEED_COPIES:
                exists = bind.execute(
                    sa.text(
                        "SELECT 1 FROM point_copy WHERE tenant_id = :tid AND copy_key = :key LIMIT 1"
                    ),
                    {"tid": tenant_id, "key": copy["copy_key"]},
                ).first()
                if exists:
                    continue
                bind.execute(
                    sa.insert(PointCopy.__table__),
                    [{"tenant_id": tenant_id, **copy}],
                )


def downgrade():
    """不删除已写入的规则（可能已被运营使用或产生流水）。"""
    pass
