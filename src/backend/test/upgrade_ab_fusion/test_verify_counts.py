"""B 基线条数必须对上映射; A 空间不得下降."""

from pathlib import Path

from test.upgrade_ab_fusion._packutil import ensure_pack_path

ensure_pack_path()
from fusion.maps import persist_runtime_maps
from fusion.verify_counts import compare_counts, expected_business_counts, map_counts


def test_expected_skips_type3():
    counts = expected_business_counts(
        {
            "knowledges": [
                {"id": "5", "type": 0},
                {"id": "9", "type": 3},
            ],
            "files": [
                {"id": "1", "knowledge_id": "5"},
                {"id": "2", "knowledge_id": "9"},
            ],
            "qas": [{"id": "3", "knowledge_id": "5"}],
            "flows": [{"id": "f"}],
            "sessions": [{"chat_id": "c1"}, {"chat_id": "c2"}],
            "messages": [
                {"id": "1", "chat_id": "c1"},
                {"id": "2", "chat_id": "gone"},
            ],
        },
        migrate_b_spaces=False,
    )
    assert counts["knowledge"] == 1
    assert counts["file"] == 1
    assert counts["qa"] == 1
    assert counts["flow"] == 1
    assert counts["session"] == 2
    assert counts["message"] == 1


def test_compare_fails_when_map_short_or_space_drops(tmp_path: Path):
    persist_runtime_maps(tmp_path, {"knowledge_maps": [{"b_id": "5", "a_id": "10"}]})
    mapped = map_counts(tmp_path)
    report = compare_counts(
        expected={"knowledge": 2, "file": 0, "qa": 0, "flow": 0, "assistant": 0},
        mapped=mapped,
        a_space_base=3,
        a_space_now=2,
    )
    assert report["ok"] is False
    assert any("空间数" in e for e in report["errors"])
    assert any("knowledge" in e for e in report["errors"])


def test_compare_fails_when_session_or_message_short(tmp_path: Path):
    persist_runtime_maps(
        tmp_path,
        {
            "session_maps": [{"b_id": "c1", "a_id": "c1"}],
            "message_maps": [{"b_id": "1", "a_id": "10"}],
        },
    )
    mapped = map_counts(tmp_path)
    report = compare_counts(
        expected={
            "knowledge": 0,
            "file": 0,
            "qa": 0,
            "flow": 0,
            "assistant": 0,
            "session": 2,
            "message": 2,
        },
        mapped=mapped,
        a_space_base=1,
        a_space_now=1,
    )
    assert report["ok"] is False
    assert any("session" in e for e in report["errors"])
    assert any("message" in e for e in report["errors"])
