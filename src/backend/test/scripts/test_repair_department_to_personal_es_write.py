# ruff: noqa: RUF001
"""Helpers for repairing department-to-personal ES write failures."""

from __future__ import annotations

from scripts import repair_department_to_personal_es_write as script


def test_detects_write_es_failed_from_metadata() -> None:
    assert script.is_write_es_failed(
        remark="迁移完成，需重新解析",
        user_metadata={
            "department_to_personal": {
                "issues": ["write ES: BulkIndexError: 2 document(s) failed to index."],
            }
        },
    )
    assert not script.is_write_es_failed(
        remark="迁移完成，需重新解析",
        user_metadata={"department_to_personal": {"issues": ["no readable index chunks; reparse required"]}},
    )


def test_index_state_classification() -> None:
    assert script.classify_index_state(12, 0) == "milvus_ready_es_missing"
    assert script.classify_index_state(12, 3) == "milvus_ready_es_partial"
    assert script.classify_index_state(12, 12) == "both_present"
    assert script.classify_index_state(0, 0) == "milvus_missing"


def test_sanitize_drops_vectors_and_keeps_ids() -> None:
    payload = script.sanitize_es_row(
        {
            "text": "hello",
            "document_id": 110858,
            "knowledge_id": 6167,
            "vector": [0.1] * 64,
            "pk": 99,
            "bbox": "1,2,3,4",
        }
    )
    assert payload["text"] == "hello"
    assert payload["metadata"]["document_id"] == 110858
    assert payload["metadata"]["knowledge_id"] == 6167
    assert payload["metadata"]["bbox"] == "1,2,3,4"
    assert "vector" not in payload["metadata"]
    assert "pk" not in payload["metadata"]


def test_cli_defaults_to_read_only_sample() -> None:
    args = script.parse_args([])
    assert args.apply is False
    assert args.all is False
    assert args.sample == 20
    assert args.file_ids == []
