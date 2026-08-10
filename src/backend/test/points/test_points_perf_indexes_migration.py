"""f082 积分性能索引迁移：元数据、索引定义与幂等性。"""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import call, patch

from bisheng.core.database.alembic.versions import (
    v2_6_0_f082_points_perf_indexes as migration,
)
from bisheng.points.domain.models.points import PointRankSnapshot, UserPointLog


def test_migration_metadata_extends_current_head() -> None:
    assert migration.revision == "f082_points_perf_indexes"
    assert migration.down_revision == "f081_points_copy_guide_only"


def test_upgrade_creates_missing_indexes_and_widens_direction_index() -> None:
    """索引缺失时全部补建，并把 ix_upl_tenant_dir_time 扩到带 delta。"""
    connection = SimpleNamespace()
    with (
        patch.object(migration.op, "get_bind", return_value=connection),
        patch.object(migration, "table_exists", return_value=True),
        patch.object(migration, "index_exists", return_value=False),
        patch.object(migration.op, "create_index") as create_index,
        patch.object(migration.op, "drop_index") as drop_index,
    ):
        migration.upgrade()

    assert create_index.call_args_list == [
        call("ix_prs_bucket", "point_rank_snapshot",
             ["tenant_id", "period", "scope", "period_key", "scope_id", "rank_no"]),
        call("ix_prs_user", "point_rank_snapshot",
             ["tenant_id", "period", "period_key", "user_id", "scope", "scope_id"]),
        call("ix_prs_refresh", "point_rank_snapshot",
             ["tenant_id", "period", "period_key", "refreshed_at"]),
        call("ix_upl_source_time", "user_point_log",
             ["tenant_id", "source", "occurred_at", "id"]),
        call("ix_upl_tenant_dir_time", "user_point_log",
             ["tenant_id", "direction", "occurred_at", "delta"]),
    ]
    # index_exists 为 False 时旧索引视为不存在，因此不会触发 drop。
    assert drop_index.call_args_list == []


@contextmanager
def fake_schema(existing: dict[str, list[str]]):
    """用可变字典模拟库里的索引，让 drop 后紧接的 create 能被正确观察到。

    真实库上 index_exists 会随 drop / create 变化，固定返回值会让「先删后建」
    的扩列逻辑被误判为跳过。yield 出的字典即迁移结束后的索引形态。
    """
    schema = dict(existing)

    def _exists(_bind, _table, name):
        return name in schema

    def _create(name, _table, columns):
        schema[name] = list(columns)

    def _drop(name, table_name=None):  # noqa: ARG001 - 与 op.drop_index 签名对齐
        schema.pop(name, None)

    with (
        patch.object(migration.op, "get_bind", return_value=SimpleNamespace()),
        patch.object(migration, "table_exists", return_value=True),
        patch.object(migration, "index_exists", side_effect=_exists),
        patch.object(migration.op, "create_index", side_effect=_create),
        patch.object(migration.op, "drop_index", side_effect=_drop),
    ):
        yield schema


def test_upgrade_reaches_same_state_when_rerun() -> None:
    """重复执行 upgrade 得到同一套索引，不重复建也不丢索引。"""
    expected = {
        "ix_prs_bucket": ["tenant_id", "period", "scope", "period_key", "scope_id", "rank_no"],
        "ix_prs_user": ["tenant_id", "period", "period_key", "user_id", "scope", "scope_id"],
        "ix_prs_refresh": ["tenant_id", "period", "period_key", "refreshed_at"],
        "ix_upl_source_time": ["tenant_id", "source", "occurred_at", "id"],
        "ix_upl_tenant_dir_time": ["tenant_id", "direction", "occurred_at", "delta"],
    }
    start = {"ix_upl_tenant_dir_time": ["tenant_id", "direction", "occurred_at"]}

    with fake_schema(start) as schema:
        migration.upgrade()
        assert schema == expected
        migration.upgrade()
        assert schema == expected


def test_upgrade_skips_when_tables_absent() -> None:
    """表还没建时迁移必须静默跳过，不能报错。"""
    connection = SimpleNamespace()
    with (
        patch.object(migration.op, "get_bind", return_value=connection),
        patch.object(migration, "table_exists", return_value=False),
        patch.object(migration.op, "create_index") as create_index,
        patch.object(migration.op, "drop_index") as drop_index,
    ):
        migration.upgrade()

    assert create_index.call_args_list == []
    assert drop_index.call_args_list == []


def test_downgrade_returns_to_f081_index_shape() -> None:
    """upgrade → downgrade 必须回到 f081 形态（三列 dir 索引，无快照索引）。"""
    start = {"ix_upl_tenant_dir_time": ["tenant_id", "direction", "occurred_at"]}
    with fake_schema(start) as schema:
        migration.upgrade()
        migration.downgrade()
        assert schema == start


def test_migration_matches_orm_table_args() -> None:
    """迁移里的索引定义必须与 ORM __table_args__ 一致，避免两边漂移。"""
    def orm_indexes(model) -> dict[str, list[str]]:
        return {
            item.name: [c.name for c in item.columns]
            for item in model.__table__.indexes
        }

    snapshot = orm_indexes(PointRankSnapshot)
    ledger = orm_indexes(UserPointLog)
    declared = {name: cols for _table, name, cols in migration.NEW_INDEXES}

    for name, cols in declared.items():
        assert snapshot.get(name) == cols or ledger.get(name) == cols, name
    assert ledger[migration.DIR_INDEX_NAME] == migration.DIR_INDEX_NEW
