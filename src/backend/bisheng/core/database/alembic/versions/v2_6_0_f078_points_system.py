"""重建积分表的幂等迁移。

Revision ID: f078_points_system
Revises: f077_knowledge_folder_sort_weight
"""

from alembic import op
import sqlalchemy as sa

from bisheng.points.domain.constants.seed_rules import SEED_COPIES, SEED_RULES
from bisheng.points.domain.models import PointCopy, PointFavoriteTierAward, PointRankSnapshot, PointRule, PointSyncOutbox, UserPointAccount, UserPointLog

revision = "f078_points_system"
down_revision = "f077_knowledge_folder_sort_weight"
branch_labels = None
depends_on = None


def table_exists(bind, name: str) -> bool:
    """跨数据库检查表是否已存在。"""
    return name in sa.inspect(bind).get_table_names()


def column_exists(bind, table: str, column: str) -> bool:
    """跨数据库检查列是否已存在。"""
    return any(item["name"] == column for item in sa.inspect(bind).get_columns(table))


def upgrade():
    """仅补齐缺失对象；已处于 f078 的数据库可安全执行此文件。"""
    bind = op.get_bind()
    if table_exists(bind, "department") and not column_exists(bind, "department", "org_level"):
        op.add_column("department", sa.Column("org_level", sa.String(16), nullable=True))
        op.create_index("ix_department_tenant_org_level", "department", ["tenant_id", "org_level"])
    for model in (UserPointAccount, UserPointLog, PointRule, PointCopy, PointRankSnapshot, PointFavoriteTierAward, PointSyncOutbox):
        if not table_exists(bind, model.__tablename__):
            model.__table__.create(bind, checkfirst=True)
    if table_exists(bind, "point_rule"):
        count = bind.execute(sa.text("SELECT COUNT(*) FROM point_rule WHERE tenant_id = 1")).scalar() or 0
        if not count:
            bind.execute(
                sa.insert(PointRule.__table__),
                [{"tenant_id": 1, "remark": None, **rule} for rule in SEED_RULES],
            )
            bind.execute(sa.insert(PointCopy.__table__), [{"tenant_id": 1, **copy} for copy in SEED_COPIES])


def downgrade():
    """开发环境逆向删除积分表；生产环境不应删除审计流水。"""
    bind = op.get_bind()
    for name in ("point_sync_outbox", "point_favorite_tier_award", "point_rank_snapshot", "point_copy", "point_rule", "user_point_log", "user_point_account"):
        if table_exists(bind, name):
            op.drop_table(name)
