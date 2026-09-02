from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import relink_duplicate_space_files_as_publish as script_mod


_SPACE_NAMES = {
    1: "公共知识库",
    2: "公共知识库B",
    10: "部门知识库",
    11: "部门知识库B",
    20: "科室知识库",
    30: "个人知识库",
}


def _space(space_id: int, level: str, name: str | None = None) -> script_mod.SpaceSnapshot:
    return script_mod.SpaceSnapshot(
        space_id=space_id,
        level=level,
        name=_SPACE_NAMES.get(space_id, f"space-{space_id}") if name is None else name,
    )


def _file(
    file_id: int,
    space_id: int,
    *,
    md5: str | None,
    file_name: str = "same.pdf",
    file_size: int = 10,
    create_time: str | None = None,
    entry_type: str | None = None,
    file_type: int = 1,
    file_level_path: str = "",
    status: int = 2,
) -> script_mod.FileSnapshot:
    return script_mod.FileSnapshot(
        file_id=file_id,
        space_id=space_id,
        file_name=file_name,
        file_size=file_size,
        md5=md5,
        status=status,
        file_type=file_type,
        entry_type=entry_type,
        create_time=create_time,
        file_level_path=file_level_path,
        storage_objects=(script_mod.StorageObjectSnapshot(kind="original", name=f"obj/{file_id}"),),
    )


def _inventory(*files: script_mod.FileSnapshot, versions=()) -> script_mod.Inventory:
    spaces = (
        _space(1, "public"),
        _space(2, "public"),
        _space(10, "department"),
        _space(11, "department"),
        _space(20, "team_ks"),
        _space(30, "personal"),
    )
    return script_mod.Inventory(spaces=spaces, files=files, versions=tuple(versions))


def test_parse_args_defaults_to_dry_run():
    args = script_mod.parse_args(["--space-id", "10", "--file-id", "201"])
    assert args.apply is False
    assert args.space_ids == [10]
    assert args.file_ids == [201]


def test_same_level_department_copies_are_not_relinked():
    plan = script_mod.build_relink_plan(
        _inventory(
            _file(100, 10, md5="same-md5"),
            _file(200, 11, md5="same-md5"),
        )
    )

    assert plan.units == ()
    assert any(item.reason_code == "same_level_only" for item in plan.skipped)


def test_cross_level_public_origin_relinks_department_and_personal():
    plan = script_mod.build_relink_plan(
        _inventory(
            _file(100, 1, md5="same-md5", create_time="2026-01-01T00:00:00"),
            _file(200, 10, md5="same-md5"),
            _file(300, 30, md5="same-md5"),
        )
    )

    assert [(item.origin_file_id, item.source_file_id, item.source_level) for item in plan.units] == [
        (100, 200, "department"),
        (100, 300, "personal"),
    ]
    assert all(item.match_kind == "md5" for item in plan.units)


def test_two_public_origins_keep_same_level_peer_and_only_relink_lower():
    plan = script_mod.build_relink_plan(
        _inventory(
            _file(101, 1, md5="same-md5", create_time="2026-01-01T00:00:00"),
            _file(102, 2, md5="same-md5", create_time="2026-02-01T00:00:00"),
            _file(200, 10, md5="same-md5"),
        )
    )

    assert len(plan.units) == 1
    assert plan.units[0].origin_file_id == 101
    assert plan.units[0].source_file_id == 200
    assert plan.units[0].kept_same_level_file_ids == (102,)


def test_empty_md5_falls_back_to_file_name_and_size():
    plan = script_mod.build_relink_plan(
        _inventory(
            _file(100, 1, md5=None, file_name="report.docx", file_size=88),
            _file(200, 10, md5="   ", file_name="report.docx", file_size=88),
            _file(201, 11, md5=None, file_name="report.docx", file_size=99),
            _file(202, 30, md5=None, file_name="other.docx", file_size=88),
        )
    )

    assert len(plan.units) == 1
    assert plan.units[0].match_kind == "name_size"
    assert plan.units[0].origin_file_id == 100
    assert plan.units[0].source_file_id == 200


def test_blank_md5_without_name_or_size_is_unmatched():
    plan = script_mod.build_relink_plan(
        _inventory(
            _file(100, 1, md5="", file_name="  ", file_size=0),
            _file(200, 10, md5=None, file_name="same.pdf", file_size=10),
        )
    )

    assert plan.unmatched_count == 1
    assert any(item.reason_code == "blank_match_key" for item in plan.skipped)
    assert plan.units == ()


def test_history_versions_are_listed_but_not_converted():
    versions = (
        script_mod.VersionSnapshot(version_id=1, document_id=9, file_id=199, version_no=1, is_primary=False),
        script_mod.VersionSnapshot(version_id=2, document_id=9, file_id=200, version_no=2, is_primary=True),
    )
    plan = script_mod.build_relink_plan(
        _inventory(
            _file(100, 1, md5="same-md5"),
            _file(199, 10, md5="unique-history"),
            _file(200, 10, md5="same-md5"),
            versions=versions,
        )
    )

    assert len(plan.units) == 1
    assert plan.units[0].source_file_id == 200
    assert plan.units[0].history_file_ids == (199,)


def test_logical_publish_entries_are_ignored_even_with_matching_name():
    plan = script_mod.build_relink_plan(
        _inventory(
            _file(100, 1, md5="same-md5"),
            _file(200, 10, md5=None, file_name="same.pdf", file_size=10, entry_type="publish"),
        )
    )
    assert plan.units == ()


async def test_apply_skips_when_revalidation_detects_drift(tmp_path: Path):
    unit = script_mod.RelinkUnit(
        match_kind="md5",
        match_key="same-md5",
        origin_file_id=100,
        origin_space_id=1,
        origin_level="public",
        source_file_id=200,
        source_space_id=10,
        source_level="department",
    )
    plan = script_mod.RelinkPlan(tenant_id=1, units=(unit,), skipped=(), unmatched_count=0)

    class Reader:
        async def build_plan(self, args):
            return plan

        async def revalidate(self, current):
            return script_mod.RevalidationResult(valid=False, reason_code="plan_drift")

    class Operations:
        def __init__(self):
            self.calls = []

        async def attach(self, current):
            self.calls.append("attach")
            return {}

        async def delete_vectors(self, current):
            self.calls.append("delete_vectors")

        async def delete_minio(self, current):
            self.calls.append("delete_minio")

        async def enqueue_projection(self, current, *, manager_file_id):
            self.calls.append("enqueue")

        async def verify_linked(self, current):
            return {}

    args = script_mod.parse_args(["--report-dir", str(tmp_path), "--apply"])
    operations = Operations()
    exit_code = await script_mod.run(
        args,
        reader=Reader(),
        operations_factory=lambda: operations,
        manage_context=False,
    )

    assert exit_code == script_mod.EXIT_OK
    assert operations.calls == []
    payload = json.loads(next(tmp_path.glob("relink-*.json")).read_text(encoding="utf-8"))
    markdown = next(tmp_path.glob("relink-*.md")).read_text(encoding="utf-8")
    assert payload["units"][0]["status"] == "skipped"
    assert payload["units"][0]["reason_code"] == "plan_drift"
    assert "跨库重复文件软链接报告" in markdown
    assert "写入前数据已变化" in markdown


async def test_apply_fails_fast_and_marks_remaining_units_pending(tmp_path: Path):
    units = tuple(
        script_mod.RelinkUnit(
            match_kind="md5",
            match_key="same-md5",
            origin_file_id=100,
            origin_space_id=1,
            origin_level="public",
            source_file_id=file_id,
            source_space_id=10,
            source_level="department",
        )
        for file_id in (200, 201)
    )
    plan = script_mod.RelinkPlan(tenant_id=1, units=units, skipped=(), unmatched_count=0)

    class Reader:
        async def build_plan(self, args):
            return plan

        async def revalidate(self, current):
            return script_mod.RevalidationResult(valid=True, unit=current)

    class Operations:
        async def attach(self, current):
            raise RuntimeError("attach failed")

        async def delete_vectors(self, current):
            return None

        async def delete_minio(self, current):
            return None

        async def enqueue_projection(self, current, *, manager_file_id):
            return None

        async def verify_linked(self, current):
            return {}

    args = script_mod.parse_args(["--report-dir", str(tmp_path), "--apply"])
    exit_code = await script_mod.run(
        args,
        reader=Reader(),
        operations_factory=Operations,
        manage_context=False,
    )

    assert exit_code == script_mod.EXIT_APPLY_ERROR
    payload = json.loads(next(tmp_path.glob("relink-*.json")).read_text(encoding="utf-8"))
    assert [item["status"] for item in payload["units"]] == ["failed", "pending"]


def test_ensure_single_tenant_rejects_multi_tenant():
    with pytest.raises(script_mod.PreflightError, match="single-tenant"):
        script_mod.ensure_single_tenant(True)


def test_render_markdown_report_includes_chinese_labels_and_history():
    versions = (
        script_mod.VersionSnapshot(version_id=1, document_id=9, file_id=199, version_no=1, is_primary=False),
        script_mod.VersionSnapshot(version_id=2, document_id=9, file_id=200, version_no=2, is_primary=True),
    )
    plan = script_mod.build_relink_plan(
        _inventory(
            _file(50, 1, md5=None, file_name="制度", file_type=0, file_size=0),
            _file(100, 1, md5="same-md5", file_name="规范.pdf", file_level_path="/50"),
            _file(60, 10, md5=None, file_name="归档", file_type=0, file_size=0),
            _file(199, 10, md5="unique-history", file_name="规范-旧版.pdf", file_level_path="/60"),
            _file(200, 10, md5="same-md5", file_name="规范.pdf", file_level_path="/60"),
            versions=versions,
        )
    )
    report = script_mod.make_run_report(
        plan,
        mode="dry-run",
        run_id="test-run",
        arguments={"apply": False},
    )
    markdown = script_mod.render_markdown_report(report)

    assert markdown.startswith("# 跨库重复文件软链接报告")
    assert "规范.pdf" in markdown
    assert "公共知识库（公共）" in markdown
    assert "部门知识库（部门）" in markdown
    assert "/制度" in markdown
    assert "/归档" in markdown
    assert "规范-旧版.pdf" in markdown
    assert "199" in markdown
    assert "200" in markdown


def test_plan_captures_file_name_space_name_and_directory():
    plan = script_mod.build_relink_plan(
        _inventory(
            _file(50, 1, md5=None, file_name="制度", file_type=0, file_size=0),
            _file(100, 1, md5="same-md5", file_name="规范.pdf", file_level_path="/50"),
            _file(200, 10, md5="same-md5", file_name="规范.pdf"),
        )
    )

    assert len(plan.units) == 1
    unit = plan.units[0]
    assert unit.origin_file_name == "规范.pdf"
    assert unit.origin_space_name == "公共知识库"
    assert unit.origin_directory == "/制度"
    assert unit.source_file_name == "规范.pdf"
    assert unit.source_space_name == "部门知识库"
    assert unit.source_directory == "根目录"


async def test_dry_run_writes_json_and_markdown(tmp_path: Path):
    plan = script_mod.build_relink_plan(
        _inventory(
            _file(100, 1, md5="same-md5"),
            _file(200, 10, md5="same-md5"),
        )
    )

    class Reader:
        async def build_plan(self, args):
            return plan

        async def revalidate(self, current):
            raise AssertionError("dry-run must not revalidate")

    args = script_mod.parse_args(["--report-dir", str(tmp_path)])
    exit_code = await script_mod.run(args, reader=Reader(), manage_context=False)

    assert exit_code == script_mod.EXIT_OK
    json_path = next(tmp_path.glob("relink-*.json"))
    markdown_path = next(tmp_path.glob("relink-*.md"))
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = markdown_path.read_text(encoding="utf-8")
    assert payload["mode"] == "dry-run"
    assert payload["summary"]["planned"] == 1
    assert payload["units"][0]["unit"]["origin_file_name"] == "same.pdf"
    assert payload["units"][0]["unit"]["origin_space_name"] == "公共知识库"
    assert payload["units"][0]["unit"]["source_directory"] == "根目录"
    assert "跨库重复文件软链接报告" in markdown
    assert "same.pdf" in markdown
    assert "公共知识库（公共）" in markdown
    assert "部门知识库（部门）" in markdown
    assert "根目录" in markdown
    assert "200" in markdown
