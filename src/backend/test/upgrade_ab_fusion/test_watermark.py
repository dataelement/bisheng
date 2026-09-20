"""水位差分与冻结漂移."""

from test.upgrade_ab_fusion._packutil import ensure_pack_path

ensure_pack_path()
from fusion.watermark import (
    diff_snapshot,
    freeze_drift,
    freeze_id_drift,
    id_select_sql,
    summary_select_sql,
)


def test_diff_created_updated_deleted():
    start = {"1": 10, "2": 20}
    freeze = {"2": 25, "3": 30}
    diff = diff_snapshot(start, freeze)
    assert diff["created"] == ["3"]
    assert diff["deleted"] == ["1"]
    assert diff["updated"] == ["2"]


def test_same_ts_is_not_updated():
    diff = diff_snapshot({"1": 10}, {"1": 10})
    assert diff["updated"] == []
    assert diff["created"] == []
    assert diff["deleted"] == []


def test_freeze_drift_detects_delete_and_insert():
    errors = freeze_drift(
        {"knowledge": {"count": "2", "max_id": "5", "max_update_ts": "100"}},
        {"knowledge": {"count": "1", "max_id": "5", "max_update_ts": "100"}},
    )
    assert any("count" in e for e in errors)


def test_freeze_id_drift_lists_changes():
    errors = freeze_id_drift({"1": 1}, {"1": 1, "2": 2})
    assert any("created" in e for e in errors)


def test_knowledge_sql_filters_type():
    sql = id_select_sql("knowledge")
    assert "type IN (0,1)" in sql
    assert "`knowledge`" in sql
    assert "chat_id" in id_select_sql("message_session")
    summary = summary_select_sql("knowledge", "knowledge")
    assert "type IN (0,1)" in summary
    audit = id_select_sql("auditlog")
    assert "`auditlog`" in audit
    assert "SELECT id AS id" in audit
