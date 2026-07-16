"""Tests for the cross-space knowledge-file move maintenance script."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import scripts.move_knowledge_space_files as script_mod
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, KnowledgeFileStatus


def _file(
    file_id: int,
    *,
    file_name: str = "doc.pdf",
    file_level_path: str = "",
    file_encoding: str = "GF-STD-SA-20260700000001",
    file_subcategory_code: str = "STD-A",
) -> KnowledgeFile:
    return KnowledgeFile(
        id=file_id,
        knowledge_id=10,
        user_id=1,
        file_name=file_name,
        file_level_path=file_level_path,
        file_encoding=file_encoding,
        file_subcategory_code=file_subcategory_code,
        file_type=1,
        status=KnowledgeFileStatus.SUCCESS.value,
        object_name=f"knowledge/10/{file_id}.pdf",
    )


def test_parse_args_supports_repeatable_filters_and_defaults_to_dry_run():
    args = script_mod.parse_args(
        [
            "--source-space-id",
            "10",
            "--source-folder-id",
            "11",
            "--source-file-id",
            "101",
            "--source-file-id",
            "102",
            "--source-category-code",
            "std",
            "--source-category-code",
            "RPT",
            "--source-subcategory-code",
            "std-a",
            "--target-space-id",
            "20",
            "--target-folder-id",
            "21",
            "--target-owner-id",
            "30",
        ]
    )

    assert args.apply is False
    assert args.source_space_id == 10
    assert args.source_folder_id == 11
    assert args.source_file_ids == [101, 102]
    assert args.source_category_codes == ["STD", "RPT"]
    assert args.source_subcategory_codes == ["STD-A"]
    assert args.target_space_id == 20
    assert args.target_folder_id == 21
    assert args.target_owner_id == 30


@pytest.mark.parametrize("value", ["0", "-1", "x"])
def test_parse_args_rejects_invalid_positive_ids(value: str):
    with pytest.raises(SystemExit):
        script_mod.parse_args(
            [
                "--source-space-id",
                value,
                "--target-space-id",
                "20",
                "--target-owner-id",
                "30",
            ]
        )


def test_validate_category_filters_requires_subcategory_to_belong_to_selected_parent():
    category_children = {
        "STD": frozenset({"STD-A", "STD-B"}),
        "RPT": frozenset({"RPT-A"}),
    }

    script_mod.validate_category_filters(
        category_children,
        parent_codes=["STD"],
        child_codes=["STD-A"],
    )

    with pytest.raises(script_mod.PreflightError, match="does not belong"):
        script_mod.validate_category_filters(
            category_children,
            parent_codes=["STD"],
            child_codes=["RPT-A"],
        )


def test_file_matches_all_provided_filter_dimensions_and_recurses_folder():
    record = _file(101, file_level_path="/11/12")
    filters = script_mod.SelectionFilters(
        source_space_id=10,
        source_folder_prefix="/11",
        file_ids=frozenset({101, 102}),
        category_codes=frozenset({"STD"}),
        subcategory_codes=frozenset({"STD-A"}),
    )

    assert script_mod.file_matches_filters(record, filters) is True
    assert (
        script_mod.file_matches_filters(
            _file(103, file_level_path="/11/12"),
            filters,
        )
        is False
    )
    assert (
        script_mod.file_matches_filters(
            _file(101, file_level_path="/110"),
            filters,
        )
        is False
    )
    assert (
        script_mod.file_matches_filters(
            _file(101, file_level_path="/11", file_subcategory_code="STD-B"),
            filters,
        )
        is False
    )


def test_partition_candidates_skips_versions_and_target_conflicts():
    files = [
        _file(1, file_name="ok.pdf"),
        _file(2, file_name="same-name.pdf"),
        _file(3, file_name="same-md5.pdf"),
        _file(4, file_name="versioned.pdf"),
    ]
    files[0].md5 = "md5-ok"
    files[1].md5 = "md5-name"
    files[2].md5 = "md5-existing"
    files[3].md5 = "md5-version"

    selected, skipped = script_mod.partition_candidates(
        files,
        versioned_file_ids={4},
        target_file_names={"same-name.pdf"},
        target_md5s={"md5-existing"},
    )

    assert [item.id for item in selected] == [1]
    assert [(item.source_file_id, item.reason_code) for item in skipped] == [
        (2, "target_name_conflict"),
        (3, "target_md5_conflict"),
        (4, "versioned_file"),
    ]


def test_count_milvus_records_uses_project_knowledge_rag(monkeypatch):
    from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag

    calls = []

    def fake_init(invoke_user_id, *, knowledge, embeddings):
        calls.append((invoke_user_id, knowledge, embeddings))
        return SimpleNamespace(col=None)

    monkeypatch.setattr(KnowledgeRag, "init_knowledge_milvus_vectorstore_sync", fake_init)
    space = SimpleNamespace(id=10)

    assert script_mod._count_milvus_records(space, 101) == 0
    assert calls[0][0:2] == (0, space)


def test_target_preview_object_name_preserves_custom_preview_suffix(monkeypatch):
    source = _file(101, file_name="portal-page.md")
    source.preview_file_object_name = "preview/101.html"
    target = _file(900, file_name="portal-page.md")
    monkeypatch.setattr(
        script_mod.KnowledgeUtils,
        "get_knowledge_preview_file_object_name",
        lambda *_args: None,
        raising=False,
    )
    monkeypatch.setattr(script_mod, "_storage_object_names", lambda _file: {"preview": "preview/101.html"})

    assert script_mod._target_preview_object_name(source, target) == "preview/900.html"


def test_target_preview_object_name_uses_canonical_supported_type(monkeypatch):
    source = _file(101, file_name="slides.pptx")
    target = _file(900, file_name="slides.pptx")
    monkeypatch.setattr(
        script_mod.KnowledgeUtils,
        "get_knowledge_preview_file_object_name",
        lambda *_args: "preview/900.pdf",
        raising=False,
    )

    assert script_mod._target_preview_object_name(source, target) == "preview/900.pdf"


class _FakeMoveOperations:
    def __init__(self, *, fail_at: str | None = None, cleanup_error: str = "") -> None:
        self.fail_at = fail_at
        self.cleanup_error = cleanup_error
        self.calls: list[str] = []
        self.target = _file(900)
        self.target.knowledge_id = 20

    async def copy_file(self, source_file: KnowledgeFile) -> KnowledgeFile:
        self.calls.append("copy")
        if self.fail_at == "copy":
            raise RuntimeError("copy failed")
        return self.target

    async def copy_tags(self, source_file: KnowledgeFile, target_file: KnowledgeFile) -> None:
        self.calls.append("tags")
        if self.fail_at == "tags":
            raise RuntimeError("tags failed")

    async def write_permissions(self, target_file: KnowledgeFile) -> None:
        self.calls.append("permissions")
        if self.fail_at == "permissions":
            raise RuntimeError("permissions failed")

    async def verify_target(self, source_file: KnowledgeFile, target_file: KnowledgeFile) -> None:
        self.calls.append("verify")
        if self.fail_at == "verify":
            raise RuntimeError("verification failed")

    async def delete_source(self, source_file: KnowledgeFile, target_file: KnowledgeFile) -> None:
        self.calls.append("delete_source")
        if self.fail_at == "delete_source":
            raise RuntimeError("source deletion failed")

    async def cleanup_target(self, target_file: KnowledgeFile) -> list[str]:
        self.calls.append("cleanup_target")
        return [self.cleanup_error] if self.cleanup_error else []


async def test_move_one_file_verifies_before_deleting_source():
    operations = _FakeMoveOperations()

    result = await script_mod.move_one_file(_file(101), operations)

    assert result.status == "success"
    assert result.target_file_id == 900
    assert result.source_deleted is True
    assert operations.calls == ["copy", "tags", "permissions", "verify", "delete_source"]


async def test_move_one_file_cleans_target_and_keeps_source_when_verification_fails():
    operations = _FakeMoveOperations(fail_at="verify")

    result = await script_mod.move_one_file(_file(101), operations)

    assert result.status == "failed"
    assert result.source_deleted is False
    assert result.target_cleanup_succeeded is True
    assert "verification failed" in result.error
    assert operations.calls == ["copy", "tags", "permissions", "verify", "cleanup_target"]


async def test_move_one_file_reports_residual_target_when_cleanup_fails():
    operations = _FakeMoveOperations(fail_at="delete_source", cleanup_error="minio residual")

    result = await script_mod.move_one_file(_file(101), operations)

    assert result.status == "failed"
    assert result.source_deleted is False
    assert result.target_cleanup_succeeded is False
    assert result.cleanup_errors == ["minio residual"]


def test_write_json_report_contains_traceable_file_results(tmp_path):
    report = script_mod.MoveRunReport(
        mode="apply",
        run_id="run-1",
        parameters={"source_space_id": 10, "target_space_id": 20},
        tenant_id=1,
        results=[
            script_mod.FileMoveResult(
                source_file_id=101,
                source_space_id=10,
                source_file_name="doc.pdf",
                status="success",
                target_space_id=20,
                target_file_id=900,
                source_deleted=True,
            )
        ],
    )

    output = script_mod.write_json_report(report, tmp_path)
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert payload["summary"] == {"failed": 0, "skipped": 0, "success": 1, "total": 1}
    assert payload["results"][0]["source_file_id"] == 101
    assert payload["results"][0]["target_file_id"] == 900


async def test_run_defaults_to_dry_run_without_constructing_move_operations(monkeypatch, tmp_path):
    args = script_mod.parse_args(
        [
            "--source-space-id",
            "10",
            "--target-space-id",
            "20",
            "--target-owner-id",
            "30",
            "--report-dir",
            str(tmp_path),
        ]
    )
    plan = script_mod.PreflightPlan(
        tenant_id=1,
        source_space=SimpleNamespace(id=10, name="source"),
        target_space=SimpleNamespace(id=20, name="target"),
        target_owner=SimpleNamespace(user_id=30, user_name="owner"),
        source_folder=None,
        target_folder=None,
        target_file_level_path="",
        target_level=0,
        selected_files=[_file(101)],
        skipped_files=[],
    )
    initialize = AsyncMock()
    close = AsyncMock()
    monkeypatch.setattr(script_mod, "initialize_app_context", initialize)
    monkeypatch.setattr(script_mod, "close_app_context", close)
    monkeypatch.setattr(script_mod, "build_preflight_plan", AsyncMock(return_value=plan))

    def fail_if_constructed(_plan):
        raise AssertionError("dry-run must not construct write operations")

    monkeypatch.setattr(script_mod, "BishengMoveOperations", fail_if_constructed)

    assert await script_mod.run(args) == script_mod.EXIT_OK
    assert initialize.await_count == 1
    assert close.await_count == 1
    reports = list(tmp_path.glob("knowledge-file-move-*.json"))
    assert len(reports) == 1
    payload = json.loads(reports[0].read_text(encoding="utf-8"))
    assert payload["mode"] == "dry-run"
    assert payload["results"][0]["reason_code"] == "dry_run_selected"
