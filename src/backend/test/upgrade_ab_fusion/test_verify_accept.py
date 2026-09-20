"""A 原数据对照与悬挂 SQL 模板."""

from test.upgrade_ab_fusion._packutil import ensure_pack_path

ensure_pack_path()
from fusion.verify_accept import compare_space_meta, dangling_checks, missing_ids


def test_compare_space_meta_detects_field_change():
    errs = compare_space_meta(
        [{"id": "3", "name": "空间", "description": "d", "user_id": "1", "tenant_id": "1", "update_time": "t"}],
        [{"id": "3", "name": "改了", "description": "d", "user_id": "1", "tenant_id": "1", "update_time": "t"}],
    )
    assert any("name" in e for e in errs)


def test_compare_space_meta_detects_missing_row():
    errs = compare_space_meta(
        [{"id": "3", "name": "空间", "description": "", "user_id": "1", "tenant_id": "1", "update_time": ""}],
        [],
    )
    assert any("消失" in e for e in errs)


def test_missing_chat_ids():
    assert missing_ids({"a", "b"}, {"b"}) == ["a"]


def test_dangling_sql_scoped_by_batch():
    checks = dangling_checks("fusion-1")
    names = [n for n, _ in checks]
    assert "knowledge.user_id" in names
    assert "session.flow_id" in names
    assert all("fusion-1" in sql for _, sql in checks)
