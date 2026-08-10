"""积分模块性能索引：排行快照补索引，流水表补概览/审计索引。

Revision ID: f082_points_perf_indexes
Revises: f081_points_copy_guide_only

背景：point_rank_snapshot 建表时未声明任何二级索引，榜单读取、「我的排名」
以及每小时刷新的整桶 DELETE 全部退化为全表扫描；user_point_log 上运营概览的
SUM(delta) 与审计列表的 source 过滤同样无可用索引。

本迁移只做加索引与扩索引，不改数据，可安全回滚。
"""

from alembic import op
import sqlalchemy as sa

revision = "f082_points_perf_indexes"
down_revision = "f081_points_copy_guide_only"
branch_labels = None
depends_on = None

# 新建索引：(表名, 索引名, 列)
NEW_INDEXES = [
    ("point_rank_snapshot", "ix_prs_bucket", ["tenant_id", "period", "scope", "period_key", "scope_id", "rank_no"]),
    ("point_rank_snapshot", "ix_prs_user", ["tenant_id", "period", "period_key", "user_id", "scope", "scope_id"]),
    ("point_rank_snapshot", "ix_prs_refresh", ["tenant_id", "period", "period_key", "refreshed_at"]),
    ("user_point_log", "ix_upl_source_time", ["tenant_id", "source", "occurred_at", "id"]),
]

# 扩列索引：末尾补 delta 后 SUM(delta) 可纯索引扫描
DIR_INDEX_TABLE = "user_point_log"
DIR_INDEX_NAME = "ix_upl_tenant_dir_time"
DIR_INDEX_OLD = ["tenant_id", "direction", "occurred_at"]
DIR_INDEX_NEW = ["tenant_id", "direction", "occurred_at", "delta"]


def table_exists(bind, name: str) -> bool:
    """跨数据库检查表是否存在。"""
    return name in sa.inspect(bind).get_table_names()


def index_exists(bind, table: str, name: str) -> bool:
    """跨数据库检查索引是否存在。"""
    return any(item["name"] == name for item in sa.inspect(bind).get_indexes(table))


def _create(bind, table: str, name: str, columns: list[str]) -> None:
    """幂等建索引：表缺失或索引已存在时跳过。"""
    if not table_exists(bind, table) or index_exists(bind, table, name):
        return
    op.create_index(name, table, columns)


def _drop(bind, table: str, name: str) -> None:
    """幂等删索引。"""
    if table_exists(bind, table) and index_exists(bind, table, name):
        op.drop_index(name, table_name=table)


def upgrade():
    """补齐缺失索引；重复执行安全。"""
    bind = op.get_bind()
    for table, name, columns in NEW_INDEXES:
        _create(bind, table, name, columns)
    # 扩列需先删后建（DM8 不支持原地改索引定义）。
    _drop(bind, DIR_INDEX_TABLE, DIR_INDEX_NAME)
    _create(bind, DIR_INDEX_TABLE, DIR_INDEX_NAME, DIR_INDEX_NEW)


def downgrade():
    """回退到 f081 的索引形态。"""
    bind = op.get_bind()
    _drop(bind, DIR_INDEX_TABLE, DIR_INDEX_NAME)
    _create(bind, DIR_INDEX_TABLE, DIR_INDEX_NAME, DIR_INDEX_OLD)
    for table, name, _columns in reversed(NEW_INDEXES):
        _drop(bind, table, name)
