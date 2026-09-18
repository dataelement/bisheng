# ruff: noqa: RUF001
"""Reason classification for the department-to-personal impact diagnosis script."""

from __future__ import annotations

import json

import pytest

from scripts import diagnose_department_to_personal_impact as script


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("embedding model changed; reparse required", "embedding_model_changed"),
        ("no readable index chunks; reparse required", "no_readable_index_chunks"),
        ("ES chunks contain no vectors; reparse required", "es_no_vectors"),
        ("read Milvus: TimeoutError: x", "read_milvus_failed"),
        ("read ES: ConnectionError: x", "read_es_failed"),
        ("write Milvus: RuntimeError: Milvus insert incomplete", "write_milvus_failed"),
        ("write ES: RuntimeError: ES refresh failed", "write_es_failed"),
        ("indexes: TimeoutError: x", "index_transfer_exception"),
        ("source parse status=3; reparse required", "source_not_success"),
        ("cleanup Milvus space=10 file=1: TimeoutError: x", "cleanup_source_milvus"),
        ("cleanup ES space=10 file=1: TimeoutError: x", "cleanup_source_es"),
        ("source indexes: TimeoutError: x", "cleanup_source_index"),
        ("overwrite indexes: RuntimeError: x", "overwrite_index_cleanup"),
        ("overwrite permissions: RuntimeError: x", "overwrite_permission_cleanup"),
        ("overwrite tags: RuntimeError: x", "overwrite_tag_cleanup"),
        ("file projections: RuntimeError: content statistics refresh enqueue failed", "projection_refresh"),
        ("unexpected boom", "other"),
    ],
)
def test_classify_issue(text: str, expected: str) -> None:
    assert script.classify_issue(text) == expected


def test_primary_reason_prefers_copy_failure_over_cleanup() -> None:
    payload = script.classify_payload(
        {
            "issues": [
                "cleanup ES space=1 file=2: TimeoutError: x",
                "embedding model changed; reparse required",
            ]
        }
    )
    assert payload["primary_reason"] == "embedding_model_changed"
    assert payload["reasons"] == ["cleanup_source_es", "embedding_model_changed"]


def test_extract_payload_from_department_metadata() -> None:
    payload = script.extract_migration_payload(
        remark="",
        user_metadata={
            "department_to_personal": {
                "source_space_id": 88,
                "via": "es",
                "issues": ["ES chunks contain no vectors; reparse required"],
            }
        },
    )
    assert payload == {
        "source": "department_to_personal",
        "via": "es",
        "source_space_id": 88,
        "issues": ["ES chunks contain no vectors; reparse required"],
    }


def test_extract_payload_from_failed_remark_json() -> None:
    remark = json.dumps(
        {
            "status_code": 10900,
            "status_message": "文件解析失败",
            "data": {"exception": "迁移完成，需重新解析: read Milvus: TimeoutError: x"},
        },
        ensure_ascii=False,
    )
    payload = script.extract_migration_payload(remark, None)
    assert payload is not None
    assert payload["source"] == "remark"
    assert payload["issues"] == ["read Milvus: TimeoutError: x"]
    assert script.classify_payload(payload)["primary_reason"] == "read_milvus_failed"


def test_extract_payload_returns_none_for_unrelated_file() -> None:
    assert script.extract_migration_payload("普通解析失败", {"other": {}}) is None


def test_conclusion_explains_homepage_gap_with_migration_failures() -> None:
    result = script.build_conclusion(
        mysql_homepage_like=20000,
        es_homepage=14000,
        es_unknown=0,
        migration_status3=5800,
        primary_counts={"embedding_model_changed": 4000, "no_readable_index_chunks": 1800},
    )
    assert result["gap"] == 6000
    assert any("5800" in line for line in result["likely_causes"])
    assert any("4000" in line or "embedding_model_changed" in line for line in result["likely_causes"])


def test_conclusion_points_at_es_lag_when_no_migration_marks() -> None:
    result = script.build_conclusion(
        mysql_homepage_like=20000,
        es_homepage=14000,
        es_unknown=100,
        migration_status3=0,
        primary_counts={},
    )
    assert any("统计快照未跟上" in line for line in result["likely_causes"])
    assert any("unknown" in line for line in result["likely_causes"])


def test_cli_is_read_only() -> None:
    args = script.parse_args([])
    assert args.skip_es is False
    assert args.sample_limit == 20
    assert not hasattr(args, "apply")
