# ruff: noqa: RUF002
"""f084 COMMENT 迁移不得剥主键自增；f088 幂等补回缺失的 AUTO_INCREMENT。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from bisheng.core.database.alembic.versions import (
    v2_6_0_f084_points_column_comments as f084,
)
from bisheng.core.database.alembic.versions import (
    v2_6_0_f088_points_restore_pk_autoincrement as f088,
)
from bisheng.points.domain.models.points import UserPointAccount


class _Result:
    """模拟 SQLAlchemy execute().mappings().first()。"""

    def __init__(self, row: dict | None):
        self._row = row

    def mappings(self):
        return self

    def first(self):
        return self._row


def _row(*, comment: str = "主键", extra: str = "", column_type: str = "bigint") -> dict:
    return {
        "COLUMN_TYPE": column_type,
        "IS_NULLABLE": "NO",
        "COLUMN_DEFAULT": None,
        "EXTRA": extra,
        "COLUMN_COMMENT": comment,
    }


def test_f088_metadata_follows_points_merge_head() -> None:
    assert f088.revision == "f088_points_restore_pk_autoincrement"
    assert f088.down_revision == "f086_merge_points_qa_images"


def test_account_id_needs_autoincrement() -> None:
    column = UserPointAccount.__table__.c.id
    assert f084._column_needs_autoincrement(column) is True


def test_f084_skips_when_comment_and_autoincrement_already_ok() -> None:
    """COMMENT 已匹配且 EXTRA 含 auto_increment 时不再 MODIFY。"""
    bind = SimpleNamespace(execute=lambda *_a, **_k: _Result(_row(extra="auto_increment")))
    with patch.object(f084.op, "execute") as execute:
        f084._apply_mysql_comment(bind, "user_point_account", "id", "主键", needs_autoincrement=True)
    execute.assert_not_called()


def test_f084_restores_autoincrement_when_comment_already_set() -> None:
    """COMMENT 已是「主键」但缺自增时仍要 MODIFY 补回 AUTO_INCREMENT。"""
    bind = SimpleNamespace(execute=lambda *_a, **_k: _Result(_row(extra="")))
    with patch.object(f084.op, "execute") as execute:
        f084._apply_mysql_comment(bind, "user_point_account", "id", "主键", needs_autoincrement=True)
    execute.assert_called_once()
    sql = str(execute.call_args.args[0])
    assert "AUTO_INCREMENT" in sql
    assert "user_point_account" in sql
    assert "COMMENT '主键'" in sql


def test_f088_upgrade_skips_non_mysql() -> None:
    bind = SimpleNamespace(dialect=SimpleNamespace(name="dm"))
    with (
        patch.object(f088.op, "get_bind", return_value=bind),
        patch.object(f088, "_apply_mysql_comment") as apply_comment,
    ):
        f088.upgrade()
    apply_comment.assert_not_called()


def test_f088_upgrade_repairs_mysql_pk() -> None:
    """MySQL 路径会对积分主键调用 COMMENT/自增补回 helper。"""
    bind = SimpleNamespace(dialect=SimpleNamespace(name="mysql"))
    tables = {model.__tablename__ for model in f088._POINT_MODELS}
    inspector = SimpleNamespace(get_table_names=lambda: list(tables))
    with (
        patch.object(f088.op, "get_bind", return_value=bind),
        patch.object(f088, "inspect", return_value=inspector),
        patch.object(f088, "_apply_mysql_comment") as apply_comment,
    ):
        f088.upgrade()
    targets = {(c.args[1], c.args[2]) for c in apply_comment.call_args_list}
    assert ("user_point_account", "id") in targets
    assert ("user_point_log", "id") in targets
    assert all(c.kwargs.get("needs_autoincrement") is True for c in apply_comment.call_args_list)
