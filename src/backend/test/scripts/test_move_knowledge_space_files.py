"""Tests for the classified public-space knowledge-file move script."""

from __future__ import annotations

import json
import stat
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import scripts.move_knowledge_space_files as script_mod
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import (
    FileType,
    KnowledgeFile,
    KnowledgeFileStatus,
)


def _space(
    space_id: int,
    name: str,
    *,
    model: str = "embedding-1",
    owner_id: int = 30,
) -> Knowledge:
    return Knowledge(
        id=space_id,
        tenant_id=1,
        user_id=owner_id,
        name=name,
        type=KnowledgeTypeEnum.SPACE.value,
        model=model,
        collection_name=f"col-{space_id}",
        index_name=f"idx-{space_id}",
    )


def _file(
    file_id: int,
    *,
    knowledge_id: int = 10,
    file_name: str = "doc.pdf",
    file_level_path: str = "",
    file_encoding: str | None = "GF-STD-SA-20260700000001",
    file_subcategory_code: str | None = "STD-A",
    status: int = KnowledgeFileStatus.SUCCESS.value,
    file_type: int = FileType.FILE.value,
    md5: str | None = None,
) -> KnowledgeFile:
    return KnowledgeFile(
        id=file_id,
        tenant_id=1,
        knowledge_id=knowledge_id,
        user_id=1,
        user_name="source-owner",
        file_name=file_name,
        file_level_path=file_level_path,
        file_encoding=file_encoding,
        file_subcategory_code=file_subcategory_code,
        file_type=file_type,
        status=status,
        md5=md5,
        object_name=f"knowledge/{knowledge_id}/{file_id}.pdf",
    )


def _folder(folder_id: int, space_id: int, name: str, *, path: str = "", level: int = 0) -> KnowledgeFile:
    return _file(
        folder_id,
        knowledge_id=space_id,
        file_name=name,
        file_level_path=path,
        file_encoding=None,
        file_subcategory_code=None,
        file_type=FileType.DIR.value,
    ).model_copy(update={"level": level})


def _portal_config():
    return SimpleNamespace(
        portal=SimpleNamespace(
            document_types=[
                SimpleNamespace(
                    code="STD",
                    label="标准规范",
                    children=[SimpleNamespace(code="STD-A", label="制度文件")],
                ),
                SimpleNamespace(
                    code="RPT",
                    label="报告",
                    children=[SimpleNamespace(code="RPT-A", label="分析报告")],
                ),
            ]
        )
    )


def _target_index(*, duplicate_space: bool = False, deep_folder_only: bool = False):
    spaces = [_space(20, "标准规范")]
    if duplicate_space:
        spaces.append(_space(21, "标准规范", owner_id=31))
    folders = [
        _folder(
            200,
            20,
            "制度文件",
            path="/199" if deep_folder_only else "",
            level=1 if deep_folder_only else 0,
        )
    ]
    owners = {
        30: SimpleNamespace(user_id=30, user_name="target-owner", delete=0),
        31: SimpleNamespace(user_id=31, user_name="other-owner", delete=0),
    }
    return script_mod.TargetRouteIndex.from_records(1, spaces, folders, owners)


def test_parse_args_accepts_multiple_source_spaces_and_defaults_to_dry_run():
    args = script_mod.parse_args(
        [
            "--source-space-id",
            "11",
            "--source-space-id",
            "10",
            "--source-space-id",
            "11",
        ]
    )

    assert args.apply is False
    assert args.source_space_ids == [10, 11]
    assert args.preserve_folder_structure is False
    assert args.folder_root_mode == "include"


@pytest.mark.parametrize("value", ["0", "-1", "x"])
def test_parse_args_rejects_invalid_positive_source_id(value: str):
    with pytest.raises(SystemExit):
        script_mod.parse_args(["--source-space-id", value])


def test_old_explicit_target_arguments_are_not_supported():
    with pytest.raises(SystemExit):
        script_mod.parse_args(
            [
                "--source-space-id",
                "10",
                "--target-space-id",
                "20",
                "--target-owner-id",
                "30",
            ]
        )


def test_parse_args_accepts_source_filters_explicit_target_and_record_options():
    args = script_mod.parse_args(
        [
            "--source-space-id",
            "10",
            "--source-folder-id",
            "202",
            "--source-folder-id",
            "201",
            "--source-folder-id",
            "202",
            "--source-category-code",
            " std ",
            "--source-category-code",
            "RPT",
            "--source-subcategory-code",
            " std-a ",
            "--target-space-id",
            "20",
            "--target-folder-id",
            "200",
            "--force-overwrite",
            "--rollback-record-file",
            "/tmp/move-record.jsonl",
            "--batch-size",
            "10",
            "--apply",
        ]
    )

    assert args.source_folder_ids == [201, 202]
    assert args.source_category_codes == ["RPT", "STD"]
    assert args.source_subcategory_codes == ["STD-A"]
    assert args.target_space_id == 20
    assert args.target_folder_id == 200
    assert args.force_overwrite is True
    assert args.rollback_record_file == Path("/tmp/move-record.jsonl")
    assert args.batch_size == 10


@pytest.mark.parametrize("root_mode", ["include", "contents"])
def test_parse_args_accepts_folder_structure_options(root_mode: str):
    args = script_mod.parse_args(
        [
            "--source-space-id",
            "10",
            "--preserve-folder-structure",
            "--folder-root-mode",
            root_mode,
        ]
    )

    assert args.preserve_folder_structure is True
    assert args.folder_root_mode == root_mode


def test_parse_args_rejects_folder_root_mode_without_structure_flag():
    with pytest.raises(SystemExit):
        script_mod.parse_args(
            [
                "--source-space-id",
                "10",
                "--folder-root-mode",
                "contents",
            ]
        )


@pytest.mark.parametrize(
    "target_args",
    [
        ["--target-space-id", "20"],
        ["--target-folder-id", "200"],
    ],
)
def test_parse_args_requires_explicit_target_pair(target_args):
    with pytest.raises(SystemExit):
        script_mod.parse_args(["--source-space-id", "10", *target_args])


def test_parse_args_defaults_force_overwrite_to_false():
    args = script_mod.parse_args(["--source-space-id", "10"])

    assert args.force_overwrite is False


@pytest.mark.parametrize(
    "target_args",
    [
        [],
        ["--target-space-id", "20"],
        ["--target-folder-id", "200"],
    ],
)
def test_parse_args_force_overwrite_requires_explicit_target_pair(target_args):
    with pytest.raises(SystemExit):
        script_mod.parse_args(
            [
                "--source-space-id",
                "10",
                *target_args,
                "--force-overwrite",
            ]
        )


def test_parse_args_force_overwrite_rejects_same_source_and_target_space():
    with pytest.raises(SystemExit):
        script_mod.parse_args(
            [
                "--source-space-id",
                "10",
                "--target-space-id",
                "10",
                "--target-folder-id",
                "200",
                "--force-overwrite",
            ]
        )


async def test_load_source_spaces_rejects_missing_space_before_planning(monkeypatch):
    class EmptySession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def exec(self, _statement):
            return SimpleNamespace(all=lambda: [])

    monkeypatch.setattr(script_mod, "get_async_db_session", EmptySession)

    with pytest.raises(script_mod.PreflightError, match="not found or not SPACE"):
        await script_mod._load_source_spaces([10])


def test_category_index_resolves_parent_and_child_labels():
    index = script_mod.CategoryLabelIndex.from_config(_portal_config())

    resolved = index.resolve(_file(101))

    assert resolved.category_code == "STD"
    assert resolved.category_label == "标准规范"
    assert resolved.subcategory_code == "STD-A"
    assert resolved.subcategory_label == "制度文件"
    assert resolved.reason_code == ""


@pytest.mark.parametrize(
    "record,reason_code",
    [
        (_file(101, file_encoding=None), "missing_category"),
        (_file(101, file_subcategory_code=None), "missing_subcategory"),
        (_file(101, file_encoding="GF-UNK-SA-20260700000001"), "unknown_category"),
        (_file(101, file_subcategory_code="STD-X"), "unknown_subcategory"),
    ],
)
def test_category_index_reports_stable_skip_reasons(record: KnowledgeFile, reason_code: str):
    resolved = script_mod.CategoryLabelIndex.from_config(_portal_config()).resolve(record)

    assert resolved.reason_code == reason_code


def test_target_route_matches_public_space_and_direct_root_folder_by_label():
    route = _target_index().resolve("标准规范", "制度文件")

    assert route.reason_code == ""
    assert route.target is not None
    assert route.target.space.id == 20
    assert route.target.folder.id == 200
    assert route.target.owner.user_id == 30
    assert route.target.file_level_path == "/200"
    assert route.target.level == 1


@pytest.mark.parametrize("format_character", ["\u200b", "\ufeff"])
def test_target_route_ignores_known_zero_width_format_characters(format_character: str):
    spaces = [_space(20, f"标准规范{format_character}")]
    folders = [_folder(200, 20, f"制度文件{format_character}")]
    owners = {30: SimpleNamespace(user_id=30, user_name="target-owner", delete=0)}
    target_index = script_mod.TargetRouteIndex.from_records(1, spaces, folders, owners)

    route = target_index.resolve("标准规范", "制度文件")

    assert route.reason_code == ""
    assert route.target is not None
    assert route.target.space.id == 20
    assert route.target.folder.id == 200


@pytest.mark.parametrize(
    "value,expected",
    [
        ("  标准规范  ", "标准规范"),
        ("标准-规范", "标准-规范"),
    ],
)
def test_normalize_label_preserves_existing_exact_match_semantics(value: str, expected: str):
    assert script_mod._normalize_label(value) == expected


@pytest.mark.parametrize(
    "target_index,category_label,subcategory_label,reason_code",
    [
        (_target_index(), "报告", "分析报告", "target_space_not_found"),
        (_target_index(duplicate_space=True), "标准规范", "制度文件", "target_space_ambiguous"),
        (_target_index(deep_folder_only=True), "标准规范", "制度文件", "target_folder_not_found"),
    ],
)
def test_target_route_reports_missing_or_ambiguous_candidates(
    target_index,
    category_label: str,
    subcategory_label: str,
    reason_code: str,
):
    assert target_index.resolve(category_label, subcategory_label).reason_code == reason_code


def test_target_route_skips_disabled_or_missing_owner():
    spaces = [_space(20, "标准规范", owner_id=30)]
    folders = [_folder(200, 20, "制度文件")]

    missing = script_mod.TargetRouteIndex.from_records(1, spaces, folders, {})
    disabled = script_mod.TargetRouteIndex.from_records(
        1,
        spaces,
        folders,
        {30: SimpleNamespace(user_id=30, user_name="owner", delete=1)},
    )

    assert missing.resolve("标准规范", "制度文件").reason_code == "target_owner_invalid"
    assert disabled.resolve("标准规范", "制度文件").reason_code == "target_owner_invalid"


@pytest.mark.parametrize("level", ["public", "department"])
def test_build_explicit_target_accepts_nested_public_or_department_folder(level: str):
    space = _space(20, "target")
    folder = _folder(200, 20, "nested", path="/150", level=1)
    target = script_mod.build_explicit_target_context(
        tenant_id=1,
        space=space,
        scope=SimpleNamespace(space_id=20, tenant_id=1, level=level),
        folder=folder,
        owner=SimpleNamespace(user_id=30, user_name="target-owner", delete=0),
    )

    assert target.file_level_path == "/150/200"
    assert target.level == 2


@pytest.mark.parametrize("level", ["team", "personal"])
def test_build_explicit_target_rejects_team_or_personal_space(level: str):
    with pytest.raises(script_mod.PreflightError, match="public or department"):
        script_mod.build_explicit_target_context(
            tenant_id=1,
            space=_space(20, "target"),
            scope=SimpleNamespace(space_id=20, tenant_id=1, level=level),
            folder=_folder(200, 20, "folder"),
            owner=SimpleNamespace(user_id=30, user_name="target-owner", delete=0),
        )


def test_planner_builds_single_file_unit_and_skips_ineligible_records():
    source_space = _space(10, "source")
    files = [
        _file(101),
        _file(102, status=KnowledgeFileStatus.FAILED.value),
        _folder(103, 10, "folder"),
    ]

    plan = script_mod.plan_migration_units(
        tenant_id=1,
        source_spaces={10: source_space},
        source_records=files,
        all_files_by_id={item.id: item for item in files},
        documents_by_id={},
        versions=[],
        category_index=script_mod.CategoryLabelIndex.from_config(_portal_config()),
        target_index=_target_index(),
        target_files=[],
    )

    assert [unit.unit_type for unit in plan.selected_units] == ["file"]
    assert [file.id for file in plan.selected_units[0].source_files] == [101]


def test_source_selection_recursively_matches_folders_and_combines_category_filters():
    selection = script_mod.SourceSelection(
        folder_prefixes=("/201", "/202/203"),
        category_codes=frozenset({"STD", "RPT"}),
        subcategory_codes=frozenset({"STD-A"}),
    )
    std_category = script_mod.CategoryResolution(
        category_code="STD",
        category_label="标准规范",
        subcategory_code="STD-A",
        subcategory_label="制度文件",
    )
    wrong_subcategory = script_mod.CategoryResolution(
        category_code="STD",
        category_label="标准规范",
        subcategory_code="STD-B",
        subcategory_label="其他",
    )

    assert selection.matches(_file(101, file_level_path="/201"), std_category)
    assert selection.matches(_file(102, file_level_path="/201/999"), std_category)
    assert selection.matches(_file(103, file_level_path="/202/203/204"), std_category)
    assert not selection.matches(_file(104, file_level_path="/202"), std_category)
    assert not selection.matches(_file(105, file_level_path="/201"), wrong_subcategory)


def test_build_source_selection_validates_folders_and_portal_category_relationships():
    args = SimpleNamespace(
        source_folder_ids=[201],
        source_category_codes=["STD"],
        source_subcategory_codes=["STD-A"],
    )
    selection = script_mod.build_source_selection(
        args,
        [_folder(201, 10, "source-folder", path="/150", level=1)],
        script_mod.CategoryLabelIndex.from_config(_portal_config()),
    )

    assert selection.folder_prefixes == ("/150/201",)
    assert selection.category_codes == frozenset({"STD"})
    assert selection.subcategory_codes == frozenset({"STD-A"})


def test_build_source_selection_rejects_missing_folder_or_invalid_category_pair():
    category_index = script_mod.CategoryLabelIndex.from_config(_portal_config())
    with pytest.raises(script_mod.PreflightError, match="source folders"):
        script_mod.build_source_selection(
            SimpleNamespace(
                source_folder_ids=[999],
                source_category_codes=[],
                source_subcategory_codes=[],
            ),
            [],
            category_index,
        )
    with pytest.raises(script_mod.PreflightError, match="do not belong"):
        script_mod.build_source_selection(
            SimpleNamespace(
                source_folder_ids=[],
                source_category_codes=["STD"],
                source_subcategory_codes=["RPT-A"],
            ),
            [],
            category_index,
        )


@pytest.mark.parametrize(
    "root_mode,expected_folder_ids",
    [
        ("include", [201, 202]),
        ("contents", [202]),
    ],
)
def test_folder_structure_resolves_relative_chain_from_selected_root(
    root_mode: str,
    expected_folder_ids: list[int],
):
    folders = [
        _folder(201, 10, "A"),
        _folder(202, 10, "B", path="/201", level=1),
    ]
    options = script_mod.build_folder_structure_options(
        SimpleNamespace(
            preserve_folder_structure=True,
            folder_root_mode=root_mode,
            source_folder_ids=[201],
        ),
        folders,
    )

    resolution = options.resolve(_file(101, file_level_path="/201/202"))

    assert resolution.reason_code == ""
    assert [folder.source_folder_id for folder in resolution.folders] == expected_folder_ids
    assert [folder.folder_name for folder in resolution.folders] == (["A", "B"] if root_mode == "include" else ["B"])


def test_folder_structure_without_selected_root_preserves_from_space_root():
    folders = [
        _folder(201, 10, "A"),
        _folder(202, 10, "B", path="/201", level=1),
    ]
    options = script_mod.build_folder_structure_options(
        SimpleNamespace(
            preserve_folder_structure=True,
            folder_root_mode="contents",
            source_folder_ids=[],
        ),
        folders,
    )

    resolution = options.resolve(_file(101, file_level_path="/201/202"))

    assert [folder.source_folder_id for folder in resolution.folders] == [201, 202]


def test_folder_structure_uses_outermost_overlapping_selected_root():
    folders = [
        _folder(201, 10, "A"),
        _folder(202, 10, "B", path="/201", level=1),
    ]
    options = script_mod.build_folder_structure_options(
        SimpleNamespace(
            preserve_folder_structure=True,
            folder_root_mode="contents",
            source_folder_ids=[201, 202],
        ),
        folders,
    )

    resolution = options.resolve(_file(101, file_level_path="/201/202"))

    assert [folder.source_folder_id for folder in resolution.folders] == [202]


def test_planner_skips_file_when_preserved_target_folder_depth_exceeds_ten():
    folders = [
        _folder(201, 10, "A"),
        _folder(202, 10, "B", path="/201", level=1),
    ]
    source_file = _file(101, file_level_path="/201/202")
    base_folder = _folder(200, 20, "target", path="/150/151/152/153/154/155/156/157/158", level=9)
    explicit_target = script_mod.TargetContext(
        tenant_id=1,
        space=_space(20, "target"),
        folder=base_folder,
        owner=SimpleNamespace(user_id=30, user_name="target-owner", delete=0),
        file_level_path=f"{base_folder.file_level_path}/200",
        level=10,
    )
    folder_structure = script_mod.build_folder_structure_options(
        SimpleNamespace(
            preserve_folder_structure=True,
            folder_root_mode="include",
            source_folder_ids=[],
        ),
        folders,
    )

    plan = script_mod.plan_migration_units(
        tenant_id=1,
        source_spaces={10: _space(10, "source")},
        source_records=[*folders, source_file],
        all_files_by_id={item.id: item for item in [*folders, source_file]},
        documents_by_id={},
        versions=[],
        category_index=script_mod.CategoryLabelIndex.from_config(_portal_config()),
        target_index=script_mod.TargetRouteIndex.from_records(1, [], [], {}),
        target_files=[],
        explicit_target=explicit_target,
        folder_structure=folder_structure,
    )

    assert plan.selected_units == []
    assert {(item.source_file_id, item.reason_code) for item in plan.skipped_files} == {
        (101, "target_folder_depth_exceeded")
    }


def test_planner_skips_version_chain_spanning_different_source_directories():
    folders = [_folder(201, 10, "A"), _folder(202, 10, "B")]
    files = [
        _file(101, file_name="same.pdf", file_level_path="/201"),
        _file(102, file_name="same.pdf", file_level_path="/202"),
    ]
    versions = [
        KnowledgeDocumentVersion(id=701, document_id=500, knowledge_file_id=101, version_no=1, is_primary=False),
        KnowledgeDocumentVersion(id=702, document_id=500, knowledge_file_id=102, version_no=2, is_primary=True),
    ]
    folder_structure = script_mod.build_folder_structure_options(
        SimpleNamespace(
            preserve_folder_structure=True,
            folder_root_mode="include",
            source_folder_ids=[],
        ),
        folders,
    )

    plan = script_mod.plan_migration_units(
        tenant_id=1,
        source_spaces={10: _space(10, "source")},
        source_records=[*folders, *files],
        all_files_by_id={item.id: item for item in [*folders, *files]},
        documents_by_id={500: KnowledgeDocument(id=500, knowledge_id=10, primary_version_id=702)},
        versions=versions,
        category_index=script_mod.CategoryLabelIndex.from_config(_portal_config()),
        target_index=_target_index(),
        target_files=[],
        folder_structure=folder_structure,
    )

    assert plan.selected_units == []
    assert {item.reason_code for item in plan.skipped_files} == {"version_chain_folder_mismatch"}


def test_planner_marks_reused_and_planned_target_folders_for_dry_run():
    source_folders = [
        _folder(201, 10, "A"),
        _folder(202, 10, "B", path="/201", level=1),
    ]
    source_file = _file(101, file_level_path="/201/202")
    target_folder_a = _folder(300, 20, "A", path="/200", level=1)
    folder_structure = script_mod.build_folder_structure_options(
        SimpleNamespace(
            preserve_folder_structure=True,
            folder_root_mode="include",
            source_folder_ids=[],
        ),
        source_folders,
    )

    plan = script_mod.plan_migration_units(
        tenant_id=1,
        source_spaces={10: _space(10, "source")},
        source_records=[*source_folders, source_file],
        all_files_by_id={item.id: item for item in [*source_folders, source_file]},
        documents_by_id={},
        versions=[],
        category_index=script_mod.CategoryLabelIndex.from_config(_portal_config()),
        target_index=_target_index(),
        target_files=[],
        target_folders=[target_folder_a],
        folder_structure=folder_structure,
    )

    unit = plan.selected_units[0]
    assert [(step.source_folder_id, step.target_folder_id, step.action) for step in unit.target_folder_plan] == [
        (201, 300, "reused"),
        (202, None, "planned"),
    ]
    dry_run_result = script_mod._dry_run_results(plan)[0]
    assert [mapping["action"] for mapping in dry_run_result.folder_mappings] == ["reused", "planned"]


def test_planner_allows_same_file_name_in_different_preserved_directories():
    source_folders = [_folder(201, 10, "A"), _folder(202, 10, "B")]
    files = [
        _file(101, file_name="same.pdf", file_level_path="/201"),
        _file(102, file_name="same.pdf", file_level_path="/202"),
    ]
    folder_structure = script_mod.build_folder_structure_options(
        SimpleNamespace(
            preserve_folder_structure=True,
            folder_root_mode="include",
            source_folder_ids=[],
        ),
        source_folders,
    )

    plan = script_mod.plan_migration_units(
        tenant_id=1,
        source_spaces={10: _space(10, "source")},
        source_records=[*source_folders, *files],
        all_files_by_id={item.id: item for item in [*source_folders, *files]},
        documents_by_id={},
        versions=[],
        category_index=script_mod.CategoryLabelIndex.from_config(_portal_config()),
        target_index=_target_index(),
        target_files=[],
        target_folders=[],
        folder_structure=folder_structure,
    )

    assert [unit.source_files[0].id for unit in plan.selected_units] == [101, 102]


def test_planner_detects_existing_file_conflict_in_fully_reused_preserved_directory():
    source_folder = _folder(201, 10, "A")
    source_file = _file(101, file_name="same.pdf", file_level_path="/201")
    target_folder = _folder(300, 20, "A", path="/200", level=1)
    existing_file = _file(900, knowledge_id=20, file_name="same.pdf", file_level_path="/200/300")
    folder_structure = script_mod.build_folder_structure_options(
        SimpleNamespace(
            preserve_folder_structure=True,
            folder_root_mode="include",
            source_folder_ids=[],
        ),
        [source_folder],
    )

    plan = script_mod.plan_migration_units(
        tenant_id=1,
        source_spaces={10: _space(10, "source")},
        source_records=[source_folder, source_file],
        all_files_by_id={201: source_folder, 101: source_file},
        documents_by_id={},
        versions=[],
        category_index=script_mod.CategoryLabelIndex.from_config(_portal_config()),
        target_index=_target_index(),
        target_files=[existing_file],
        target_folders=[target_folder],
        folder_structure=folder_structure,
    )

    assert plan.selected_units == []
    assert {(item.source_file_id, item.reason_code) for item in plan.skipped_files} == {(101, "target_name_conflict")}


def test_planner_applies_folder_and_category_filters_as_an_intersection():
    files = [
        _file(101, file_level_path="/201"),
        _file(102, file_level_path="/201/202", file_encoding="GF-RPT-SA-20260700000001", file_subcategory_code="RPT-A"),
        _file(103, file_level_path="/999"),
    ]
    plan = script_mod.plan_migration_units(
        tenant_id=1,
        source_spaces={10: _space(10, "source")},
        source_records=files,
        all_files_by_id={item.id: item for item in files},
        documents_by_id={},
        versions=[],
        category_index=script_mod.CategoryLabelIndex.from_config(_portal_config()),
        target_index=_target_index(),
        target_files=[],
        source_selection=script_mod.SourceSelection(
            folder_prefixes=("/201",),
            category_codes=frozenset({"STD"}),
            subcategory_codes=frozenset({"STD-A"}),
        ),
    )

    assert [unit.source_files[0].id for unit in plan.selected_units] == [101]
    assert plan.skipped_files == []
    assert plan.scanned_file_count == 3
    assert plan.source_selected_file_count == 1


def test_eligible_source_file_query_limits_rows_to_selected_folder_subtree():
    statement = script_mod._eligible_source_file_statement([10], ["/201"])

    sql = str(statement.compile(compile_kwargs={"literal_binds": True}))

    assert "knowledgefile.knowledge_id IN (10)" in sql
    assert "knowledgefile.file_type = 1" in sql
    assert "knowledgefile.status = 2" in sql
    assert "knowledgefile.file_level_path = '/201'" in sql
    assert "knowledgefile.file_level_path LIKE '/201/%'" in sql


def test_migration_plan_rejects_inconsistent_source_selection_counts():
    with pytest.raises(ValueError, match="source-selected files must equal"):
        script_mod.MigrationPlan(
            tenant_id=1,
            source_spaces={10: _space(10, "source")},
            selected_units=[],
            skipped_files=[],
            scanned_file_count=3,
            source_selected_file_count=2,
        )


def test_planner_skips_whole_version_chain_when_one_version_misses_source_filter():
    files = [_file(101, file_level_path="/201"), _file(102, file_level_path="/999")]
    versions = [
        KnowledgeDocumentVersion(id=701, document_id=500, knowledge_file_id=101, version_no=1, is_primary=False),
        KnowledgeDocumentVersion(id=702, document_id=500, knowledge_file_id=102, version_no=2, is_primary=True),
    ]
    plan = script_mod.plan_migration_units(
        tenant_id=1,
        source_spaces={10: _space(10, "source")},
        source_records=files,
        all_files_by_id={item.id: item for item in files},
        documents_by_id={500: KnowledgeDocument(id=500, knowledge_id=10, primary_version_id=702)},
        versions=versions,
        category_index=script_mod.CategoryLabelIndex.from_config(_portal_config()),
        target_index=_target_index(),
        target_files=[],
        source_selection=script_mod.SourceSelection(folder_prefixes=("/201",)),
    )

    assert plan.selected_units == []
    assert [(item.source_file_id, item.reason_code) for item in plan.skipped_files] == [
        (101, "version_chain_filter_mismatch")
    ]
    assert plan.scanned_file_count == 2
    assert plan.source_selected_file_count == 1


def test_planner_uses_explicit_target_without_relaxing_classification_rules():
    explicit_target = _target_index().resolve("标准规范", "制度文件").target
    valid = _file(101)
    invalid = _file(102, file_subcategory_code=None)
    plan = script_mod.plan_migration_units(
        tenant_id=1,
        source_spaces={10: _space(10, "source")},
        source_records=[valid, invalid],
        all_files_by_id={101: valid, 102: invalid},
        documents_by_id={},
        versions=[],
        category_index=script_mod.CategoryLabelIndex.from_config(_portal_config()),
        target_index=script_mod.TargetRouteIndex.from_records(1, [], [], {}),
        target_files=[],
        explicit_target=explicit_target,
    )

    assert [unit.source_files[0].id for unit in plan.selected_units] == [101]
    assert {(item.source_file_id, item.reason_code) for item in plan.skipped_files} == {(102, "missing_subcategory")}


def test_planner_groups_and_preserves_a_complete_version_chain():
    source_space = _space(10, "source")
    files = [_file(101, file_name="same.pdf"), _file(102, file_name="same.pdf")]
    document = KnowledgeDocument(id=500, knowledge_id=10, file_level_path="", level=0, primary_version_id=702)
    versions = [
        KnowledgeDocumentVersion(id=701, document_id=500, knowledge_file_id=101, version_no=1, is_primary=False),
        KnowledgeDocumentVersion(id=702, document_id=500, knowledge_file_id=102, version_no=2, is_primary=True),
    ]

    plan = script_mod.plan_migration_units(
        tenant_id=1,
        source_spaces={10: source_space},
        source_records=files,
        all_files_by_id={item.id: item for item in files},
        documents_by_id={500: document},
        versions=versions,
        category_index=script_mod.CategoryLabelIndex.from_config(_portal_config()),
        target_index=_target_index(),
        target_files=[],
    )

    assert len(plan.selected_units) == 1
    unit = plan.selected_units[0]
    assert unit.unit_type == "version_chain"
    assert unit.source_document.id == 500
    assert [version.version_no for version in unit.source_versions] == [1, 2]
    assert [file.id for file in unit.source_files] == [101, 102]


@pytest.mark.parametrize(
    "versions,primary_version_id",
    [
        (
            [
                KnowledgeDocumentVersion(
                    id=701,
                    document_id=500,
                    knowledge_file_id=101,
                    version_no=1,
                    is_primary=False,
                ),
                KnowledgeDocumentVersion(
                    id=702,
                    document_id=500,
                    knowledge_file_id=102,
                    version_no=2,
                    is_primary=False,
                ),
            ],
            702,
        ),
        (
            [
                KnowledgeDocumentVersion(
                    id=701,
                    document_id=500,
                    knowledge_file_id=101,
                    version_no=1,
                    is_primary=True,
                ),
                KnowledgeDocumentVersion(
                    id=702,
                    document_id=500,
                    knowledge_file_id=102,
                    version_no=2,
                    is_primary=True,
                ),
            ],
            702,
        ),
        (
            [
                KnowledgeDocumentVersion(
                    id=701,
                    document_id=500,
                    knowledge_file_id=101,
                    version_no=1,
                    is_primary=False,
                ),
                KnowledgeDocumentVersion(
                    id=702,
                    document_id=500,
                    knowledge_file_id=102,
                    version_no=2,
                    is_primary=True,
                ),
            ],
            701,
        ),
    ],
)
def test_planner_skips_corrupt_source_version_graph(versions, primary_version_id: int):
    files = [_file(101), _file(102)]

    plan = script_mod.plan_migration_units(
        tenant_id=1,
        source_spaces={10: _space(10, "source")},
        source_records=files,
        all_files_by_id={item.id: item for item in files},
        documents_by_id={
            500: KnowledgeDocument(
                id=500,
                knowledge_id=10,
                primary_version_id=primary_version_id,
            )
        },
        versions=versions,
        category_index=script_mod.CategoryLabelIndex.from_config(_portal_config()),
        target_index=_target_index(),
        target_files=[],
    )

    assert plan.selected_units == []
    assert {item.reason_code for item in plan.skipped_files} == {"version_chain_invalid_graph"}


def test_planner_requires_identical_categories_even_when_labels_route_to_same_target():
    config = _portal_config()
    config.portal.document_types.append(
        SimpleNamespace(
            code="ALT",
            label="标准规范",
            children=[SimpleNamespace(code="ALT-A", label="制度文件")],
        )
    )
    files = [
        _file(101),
        _file(
            102,
            file_encoding="GF-ALT-SA-20260700000001",
            file_subcategory_code="ALT-A",
        ),
    ]
    versions = [
        KnowledgeDocumentVersion(
            id=701,
            document_id=500,
            knowledge_file_id=101,
            version_no=1,
            is_primary=False,
        ),
        KnowledgeDocumentVersion(
            id=702,
            document_id=500,
            knowledge_file_id=102,
            version_no=2,
            is_primary=True,
        ),
    ]

    plan = script_mod.plan_migration_units(
        tenant_id=1,
        source_spaces={10: _space(10, "source")},
        source_records=files,
        all_files_by_id={item.id: item for item in files},
        documents_by_id={500: KnowledgeDocument(id=500, knowledge_id=10, primary_version_id=702)},
        versions=versions,
        category_index=script_mod.CategoryLabelIndex.from_config(config),
        target_index=_target_index(),
        target_files=[],
    )

    assert plan.selected_units == []
    assert {item.reason_code for item in plan.skipped_files} == {"version_chain_classification_mismatch"}


def test_version_chain_target_skip_preserves_category_and_route_failure_detail():
    class CountingTargetIndex:
        def __init__(self):
            self.calls: list[tuple[str, str]] = []

        def resolve(self, category_label: str, subcategory_label: str):
            self.calls.append((category_label, subcategory_label))
            return script_mod.RouteResolution(
                reason_code="target_folder_not_found",
                reason="no direct root folder matches the second-level category label",
            )

    files = [_file(101), _file(102)]
    versions = [
        KnowledgeDocumentVersion(
            id=701,
            document_id=500,
            knowledge_file_id=101,
            version_no=1,
            is_primary=False,
        ),
        KnowledgeDocumentVersion(
            id=702,
            document_id=500,
            knowledge_file_id=102,
            version_no=2,
            is_primary=True,
        ),
    ]
    target_index = CountingTargetIndex()

    plan = script_mod.plan_migration_units(
        tenant_id=1,
        source_spaces={10: _space(10, "source")},
        source_records=files,
        all_files_by_id={item.id: item for item in files},
        documents_by_id={500: KnowledgeDocument(id=500, knowledge_id=10, primary_version_id=702)},
        versions=versions,
        category_index=script_mod.CategoryLabelIndex.from_config(_portal_config()),
        target_index=target_index,
        target_files=[],
    )

    assert plan.selected_units == []
    assert target_index.calls == [("标准规范", "制度文件")]
    assert len(plan.skipped_files) == 2
    for item in plan.skipped_files:
        assert item.reason_code == "version_chain_target_unresolved"
        assert item.category_code == "STD"
        assert item.category_label == "标准规范"
        assert item.subcategory_code == "STD-A"
        assert item.subcategory_label == "制度文件"
        assert item.reason == ("target_folder_not_found: no direct root folder matches the second-level category label")


@pytest.mark.parametrize(
    "all_files,reason_code",
    [
        (
            {
                101: _file(101),
                102: _file(102, knowledge_id=99),
            },
            "version_chain_out_of_scope",
        ),
        (
            {
                101: _file(101),
                102: _file(102, status=KnowledgeFileStatus.FAILED.value),
            },
            "version_chain_ineligible_file",
        ),
        (
            {
                101: _file(101),
                102: _file(102, file_subcategory_code="RPT-A", file_encoding="GF-RPT-SA-20260700000001"),
            },
            "version_chain_classification_mismatch",
        ),
    ],
)
def test_planner_skips_entire_invalid_version_chain(all_files, reason_code: str):
    source_space = _space(10, "source")
    document = KnowledgeDocument(id=500, knowledge_id=10, primary_version_id=702)
    versions = [
        KnowledgeDocumentVersion(id=701, document_id=500, knowledge_file_id=101, version_no=1, is_primary=False),
        KnowledgeDocumentVersion(id=702, document_id=500, knowledge_file_id=102, version_no=2, is_primary=True),
    ]
    source_records = [item for item in all_files.values() if item.knowledge_id == 10]
    target_index = _target_index()
    if reason_code == "version_chain_classification_mismatch":
        target_index = script_mod.TargetRouteIndex.from_records(
            1,
            [_space(20, "标准规范"), _space(21, "报告", owner_id=31)],
            [_folder(200, 20, "制度文件"), _folder(201, 21, "分析报告")],
            {
                30: SimpleNamespace(user_id=30, user_name="owner", delete=0),
                31: SimpleNamespace(user_id=31, user_name="owner2", delete=0),
            },
        )

    plan = script_mod.plan_migration_units(
        tenant_id=1,
        source_spaces={10: source_space},
        source_records=source_records,
        all_files_by_id=all_files,
        documents_by_id={500: document},
        versions=versions,
        category_index=script_mod.CategoryLabelIndex.from_config(_portal_config()),
        target_index=target_index,
        target_files=[],
    )

    assert plan.selected_units == []
    assert {item.reason_code for item in plan.skipped_files} == {reason_code}


def test_planner_skips_model_name_and_md5_conflicts_deterministically():
    source_spaces = {
        10: _space(10, "source-a"),
        11: _space(11, "source-b"),
        12: _space(12, "source-c", model="embedding-other"),
    }
    files = [
        _file(101, knowledge_id=10, file_name="first.pdf", md5="same-batch"),
        _file(102, knowledge_id=11, file_name="second.pdf", md5="same-batch"),
        _file(103, knowledge_id=10, file_name="existing-name.pdf", md5="new"),
        _file(104, knowledge_id=10, file_name="existing-md5.pdf", md5="existing"),
        _file(105, knowledge_id=12, file_name="model.pdf", md5="model"),
    ]
    target_files = [
        _file(900, knowledge_id=20, file_name="existing-name.pdf", file_level_path="/200", md5="target-a"),
        _file(901, knowledge_id=20, file_name="other.pdf", file_level_path="/200", md5="existing"),
    ]

    plan = script_mod.plan_migration_units(
        tenant_id=1,
        source_spaces=source_spaces,
        source_records=list(reversed(files)),
        all_files_by_id={item.id: item for item in files},
        documents_by_id={},
        versions=[],
        category_index=script_mod.CategoryLabelIndex.from_config(_portal_config()),
        target_index=_target_index(),
        target_files=target_files,
    )

    assert [unit.source_files[0].id for unit in plan.selected_units] == [101]
    assert {(item.source_file_id, item.reason_code) for item in plan.skipped_files} == {
        (102, "batch_md5_conflict"),
        (103, "target_name_conflict"),
        (104, "target_md5_conflict"),
        (105, "embedding_model_mismatch"),
    }


def test_force_overwrite_plans_one_legacy_target_document():
    source = _file(101, file_name="existing-name.pdf", md5="source-md5")
    existing = _file(
        900,
        knowledge_id=20,
        file_name="existing-name.pdf",
        file_level_path="/200",
        md5="target-md5",
    )

    plan = script_mod.plan_migration_units(
        tenant_id=1,
        source_spaces={10: _space(10, "source")},
        source_records=[source],
        all_files_by_id={source.id: source},
        documents_by_id={},
        versions=[],
        category_index=script_mod.CategoryLabelIndex.from_config(_portal_config()),
        target_index=_target_index(),
        target_files=[existing],
        force_overwrite=True,
    )

    assert len(plan.selected_units) == 1
    overwrite = plan.selected_units[0].overwrite_target
    assert overwrite is not None
    assert overwrite.logical_id == "file:900"
    assert overwrite.document is None
    assert [item.id for item in overwrite.files] == [900]
    assert overwrite.matched_file_ids == (900,)
    assert overwrite.match_reasons == ("name",)


def test_force_overwrite_expands_one_matching_target_to_its_complete_version_chain():
    source = _file(101, file_name="incoming.pdf", md5="same-md5")
    target_files = [
        _file(900, knowledge_id=20, file_name="old-v1.pdf", file_level_path="/200", md5="same-md5"),
        _file(901, knowledge_id=20, file_name="old-v2.pdf", file_level_path="/200", md5="old-v2"),
    ]
    target_versions = [
        KnowledgeDocumentVersion(
            id=801,
            document_id=800,
            knowledge_file_id=900,
            version_no=1,
            is_primary=False,
        ),
        KnowledgeDocumentVersion(
            id=802,
            document_id=800,
            knowledge_file_id=901,
            version_no=2,
            is_primary=True,
        ),
    ]
    target_document = KnowledgeDocument(id=800, knowledge_id=20, primary_version_id=802)

    plan = script_mod.plan_migration_units(
        tenant_id=1,
        source_spaces={10: _space(10, "source")},
        source_records=[source],
        all_files_by_id={source.id: source},
        documents_by_id={},
        versions=[],
        category_index=script_mod.CategoryLabelIndex.from_config(_portal_config()),
        target_index=_target_index(),
        target_files=target_files,
        target_documents_by_id={800: target_document},
        target_versions=target_versions,
        force_overwrite=True,
    )

    overwrite = plan.selected_units[0].overwrite_target
    assert overwrite is not None
    assert overwrite.logical_id == "document:800"
    assert overwrite.document == target_document
    assert [item.id for item in overwrite.files] == [900, 901]
    assert [item.id for item in overwrite.versions] == [801, 802]
    assert overwrite.matched_file_ids == (900,)
    assert overwrite.match_reasons == ("md5",)


def test_force_overwrite_skips_when_conflicts_span_multiple_logical_documents():
    source = _file(101, file_name="conflict.pdf", md5="same-md5")
    target_files = [
        _file(900, knowledge_id=20, file_name="conflict.pdf", file_level_path="/200", md5="other"),
        _file(901, knowledge_id=20, file_name="elsewhere.pdf", file_level_path="/999", md5="same-md5"),
    ]

    plan = script_mod.plan_migration_units(
        tenant_id=1,
        source_spaces={10: _space(10, "source")},
        source_records=[source],
        all_files_by_id={source.id: source},
        documents_by_id={},
        versions=[],
        category_index=script_mod.CategoryLabelIndex.from_config(_portal_config()),
        target_index=_target_index(),
        target_files=target_files,
        force_overwrite=True,
    )

    assert plan.selected_units == []
    assert [(item.source_file_id, item.reason_code) for item in plan.skipped_files] == [
        (101, "target_overwrite_ambiguous")
    ]


def test_force_overwrite_reserves_one_target_document_for_the_first_source_unit():
    source_files = [
        _file(101, file_name="incoming-a.pdf", md5="old-v1"),
        _file(102, file_name="incoming-b.pdf", md5="old-v2"),
    ]
    target_files = [
        _file(900, knowledge_id=20, file_name="old-v1.pdf", file_level_path="/200", md5="old-v1"),
        _file(901, knowledge_id=20, file_name="old-v2.pdf", file_level_path="/200", md5="old-v2"),
    ]
    target_versions = [
        KnowledgeDocumentVersion(
            id=801,
            document_id=800,
            knowledge_file_id=900,
            version_no=1,
            is_primary=False,
        ),
        KnowledgeDocumentVersion(
            id=802,
            document_id=800,
            knowledge_file_id=901,
            version_no=2,
            is_primary=True,
        ),
    ]

    plan = script_mod.plan_migration_units(
        tenant_id=1,
        source_spaces={10: _space(10, "source")},
        source_records=source_files,
        all_files_by_id={item.id: item for item in source_files},
        documents_by_id={},
        versions=[],
        category_index=script_mod.CategoryLabelIndex.from_config(_portal_config()),
        target_index=_target_index(),
        target_files=target_files,
        target_documents_by_id={800: KnowledgeDocument(id=800, knowledge_id=20, primary_version_id=802)},
        target_versions=target_versions,
        force_overwrite=True,
    )

    assert [unit.source_files[0].id for unit in plan.selected_units] == [101]
    assert [(item.source_file_id, item.reason_code) for item in plan.skipped_files] == [
        (102, "batch_overwrite_conflict")
    ]


def test_target_preview_object_name_preserves_custom_preview_suffix(monkeypatch):
    source = _file(101, file_name="portal-page.md")
    source.preview_file_object_name = "preview/101.html"
    target = _file(900, knowledge_id=20, file_name="portal-page.md")
    monkeypatch.setattr(
        script_mod.KnowledgeUtils,
        "get_knowledge_preview_file_object_name",
        lambda *_args: None,
        raising=False,
    )
    monkeypatch.setattr(script_mod, "_storage_object_names", lambda _file: {"preview": "preview/101.html"})

    assert script_mod._target_preview_object_name(source, target) == "preview/900.html"


def test_storage_exists_uses_managed_minio_storage(monkeypatch):
    class FakeMinioStorage:
        bucket = "knowledge"

        def __init__(self):
            self.calls: list[tuple[str, str]] = []

        def object_exists_sync(self, bucket_name, object_name):
            self.calls.append((bucket_name, object_name))
            return object_name in {"source.pdf", "preview.html"}

    storage = FakeMinioStorage()
    monkeypatch.setattr(script_mod, "get_minio_storage_sync", lambda: storage, raising=False)
    monkeypatch.setattr(
        script_mod,
        "_storage_object_names",
        lambda _file: {
            "original": "source.pdf",
            "converted": "",
            "bbox": "missing-bbox.json",
            "preview": "preview.html",
        },
    )

    result = script_mod._storage_exists(_file(101))

    assert result == {"original": True, "converted": False, "bbox": False, "preview": True}
    assert storage.calls == [
        ("knowledge", "source.pdf"),
        ("knowledge", "missing-bbox.json"),
        ("knowledge", "preview.html"),
    ]


def test_overwrite_object_names_only_uses_legacy_file_metadata(monkeypatch):
    file = _file(101).model_copy(
        update={
            "thumbnails": "thumbnails/101.png",
            "user_metadata": {"pdf_preview_object_name": "preview/101.pdf"},
        }
    )
    monkeypatch.setattr(
        script_mod,
        "_storage_object_names",
        lambda _file: {
            "original": "source.pdf",
            "converted": "101",
            "bbox": "101.bbox",
            "preview": "preview/101.html",
        },
    )

    assert script_mod._overwrite_object_names(file) == (
        "101",
        "101.bbox",
        "preview/101.html",
        "preview/101.pdf",
        "source.pdf",
        "thumbnails/101.png",
    )


def test_copy_object_if_present_uses_managed_minio_storage(monkeypatch):
    class FakeMinioStorage:
        bucket = "knowledge"

        def __init__(self):
            self.copy_calls: list[dict[str, str]] = []

        def object_exists_sync(self, bucket_name, object_name):
            assert bucket_name == self.bucket
            return object_name == "source-preview.html"

        def copy_object_sync(self, **kwargs):
            self.copy_calls.append(kwargs)

    storage = FakeMinioStorage()
    monkeypatch.setattr(script_mod, "get_minio_storage_sync", lambda: storage, raising=False)

    script_mod._copy_object_if_present("source-preview.html", "target-preview.html")
    script_mod._copy_object_if_present("missing-preview.html", "unused.html")

    assert storage.copy_calls == [
        {
            "source_bucket": "knowledge",
            "source_object": "source-preview.html",
            "dest_bucket": "knowledge",
            "dest_object": "target-preview.html",
        }
    ]


def test_target_permissions_contain_only_owner_and_parent_relations():
    target = _target_index().resolve("标准规范", "制度文件").target
    target_file = _file(900, knowledge_id=20)

    rows = script_mod.BishengMoveOperations._target_permission_rows(target_file, target)

    assert rows == (
        {"user": "user:30", "relation": "owner", "object": "knowledge_file:900"},
        {"user": "folder:200", "relation": "parent", "object": "knowledge_file:900"},
    )


def test_new_folder_permissions_contain_target_owner_and_parent_relations():
    target = _target_index().resolve("标准规范", "制度文件").target
    folder = _folder(300, 20, "A", path="/200", level=1)

    rows = script_mod._target_folder_permission_rows(folder, target.folder, target)

    assert rows == (
        {"user": "user:30", "relation": "owner", "object": "folder:300"},
        {"user": "folder:200", "relation": "parent", "object": "folder:300"},
    )


class _FakeTargetFolderStore:
    def __init__(self, folders=()):
        self.folders = list(folders)
        self.next_id = 301
        self.permission_calls: list[tuple[int, int]] = []
        self.deleted_ids: list[int] = []
        self.nonempty_ids: set[int] = set()
        self.fail_permissions = False

    async def list_folders(self, space_id):
        return [folder for folder in self.folders if int(folder.knowledge_id) == int(space_id)]

    async def create_folder_record(self, source_folder, parent_folder, target):
        created = _folder(
            self.next_id,
            int(target.space.id),
            source_folder.folder_name,
            path=script_mod._folder_child_path(parent_folder),
            level=int(parent_folder.level or 0) + 1,
        ).model_copy(
            update={
                "user_id": int(target.owner.user_id),
                "user_name": target.owner.user_name,
                "updater_id": int(target.owner.user_id),
                "updater_name": target.owner.user_name,
            }
        )
        self.next_id += 1
        self.folders.append(created)
        return created

    async def write_folder_permissions(self, folder, parent_folder, target):
        self.permission_calls.append((int(folder.id), int(parent_folder.id)))
        if self.fail_permissions:
            raise RuntimeError("folder permission failed")

    async def is_folder_empty(self, folder):
        return int(folder.id) not in self.nonempty_ids

    async def delete_folder(self, folder):
        self.deleted_ids.append(int(folder.id))
        self.folders = [item for item in self.folders if int(item.id) != int(folder.id)]


def _folder_structure_unit():
    return script_mod.MigrationUnit(
        unit_id="file:101",
        unit_type="file",
        source_files=(_file(101, file_level_path="/201/202"),),
        target=_target_index().resolve("标准规范", "制度文件").target,
        category_code="STD",
        category_label="标准规范",
        subcategory_code="STD-A",
        subcategory_label="制度文件",
        source_folder_chain=(
            script_mod.SourceFolderRef(201, "A", "/201", 0),
            script_mod.SourceFolderRef(202, "B", "/201/202", 1),
        ),
    )


async def test_target_folder_manager_reuses_existing_and_creates_missing_directories():
    existing = _folder(300, 20, "A", path="/200", level=1)
    store = _FakeTargetFolderStore([existing])
    manager = script_mod.TargetFolderManager(store)

    prepared = await manager.prepare_unit(_folder_structure_unit())
    mappings = manager.get_unit_mappings("file:101")

    assert int(prepared.target.folder.id) == 301
    assert prepared.target.file_level_path == "/200/300/301"
    assert prepared.target.level == 3
    assert [(mapping.source_folder_id, mapping.target_folder_id, mapping.action) for mapping in mappings] == [
        (201, 300, "reused"),
        (202, 301, "created"),
    ]
    assert store.permission_calls == [(301, 300)]

    assert await manager.cleanup_unit_folders("file:101") == []
    assert store.deleted_ids == [301]


async def test_target_folder_manager_prepare_is_idempotent_for_the_same_unit():
    store = _FakeTargetFolderStore()
    manager = script_mod.TargetFolderManager(store)
    unit = _folder_structure_unit()

    first = await manager.prepare_unit(unit)
    second = await manager.prepare_unit(unit)

    assert int(first.target.folder.id) == 302
    assert int(second.target.folder.id) == 302
    assert second.target.file_level_path == "/200/301/302"
    assert store.permission_calls == [(301, 200), (302, 301)]


async def test_target_folder_manager_preserves_new_nonempty_directory_during_cleanup():
    store = _FakeTargetFolderStore()
    manager = script_mod.TargetFolderManager(store)
    await manager.prepare_unit(_folder_structure_unit())
    mappings = manager.get_unit_mappings("file:101")
    store.nonempty_ids.add(mappings[-1].target_folder_id)

    errors = await manager.cleanup_unit_folders("file:101")

    assert "not empty" in errors[0]
    assert store.deleted_ids == []


async def test_target_folder_manager_keeps_created_mapping_when_permission_write_fails():
    store = _FakeTargetFolderStore()
    store.fail_permissions = True
    manager = script_mod.TargetFolderManager(store)

    with pytest.raises(RuntimeError, match="folder permission failed"):
        await manager.prepare_unit(_folder_structure_unit())

    mappings = manager.get_unit_mappings("file:101")
    assert mappings[0].action == "created"
    assert await manager.cleanup_unit_folders("file:101") == []
    assert store.deleted_ids == [301]


async def test_database_target_folder_store_creates_target_owned_folder_record(monkeypatch):
    target = _target_index().resolve("标准规范", "制度文件").target
    created = _folder(301, 20, "A", path="/200", level=1)
    add_file = AsyncMock(return_value=created)
    monkeypatch.setattr(script_mod.KnowledgeFileDao, "aadd_file", add_file)

    result = await script_mod.DatabaseTargetFolderStore().create_folder_record(
        script_mod.SourceFolderRef(201, "A", "/201", 0),
        target.folder,
        target,
    )

    assert result is created
    record = add_file.await_args.args[0]
    assert record.tenant_id == 1
    assert record.knowledge_id == 20
    assert record.user_id == 30
    assert record.user_name == "target-owner"
    assert record.updater_id == 30
    assert record.updater_name == "target-owner"
    assert record.file_name == "A"
    assert record.file_type == FileType.DIR.value
    assert record.file_level_path == "/200"
    assert record.level == 1
    assert record.status == KnowledgeFileStatus.SUCCESS.value


async def test_database_target_folder_store_writes_owner_and_parent_permissions(monkeypatch):
    target = _target_index().resolve("标准规范", "制度文件").target
    folder = _folder(301, 20, "A", path="/200", level=1)
    replace_permissions = AsyncMock()
    monkeypatch.setattr(script_mod, "_replace_resource_permission_tuples", replace_permissions)

    await script_mod.DatabaseTargetFolderStore().write_folder_permissions(
        folder,
        target.folder,
        target,
    )

    replace_permissions.assert_awaited_once_with(
        "folder:301",
        (
            {"user": "user:30", "relation": "owner", "object": "folder:301"},
            {"user": "folder:200", "relation": "parent", "object": "folder:301"},
        ),
    )


async def test_database_target_folder_store_deletes_permissions_before_folder_record(monkeypatch):
    folder = _folder(301, 20, "A", path="/200", level=1)
    replace_permissions = AsyncMock()
    delete_batch = AsyncMock()
    monkeypatch.setattr(script_mod, "_replace_resource_permission_tuples", replace_permissions)
    monkeypatch.setattr(script_mod.KnowledgeFileDao, "adelete_batch", delete_batch)

    await script_mod.DatabaseTargetFolderStore().delete_folder(folder)

    replace_permissions.assert_awaited_once_with("folder:301", ())
    delete_batch.assert_awaited_once_with([301])


async def test_copy_file_sets_target_owner_and_folder_context(monkeypatch):
    source = _file(101)
    target = _target_index().resolve("标准规范", "制度文件").target
    copied = _file(900, knowledge_id=20)
    operations = script_mod.BishengMoveOperations(1, {10: _space(10, "source")})
    snapshot = script_mod.SourceSnapshot(
        tags=script_mod.TagSnapshot(),
        permissions=(),
        indexes=script_mod.IndexSnapshot(milvus_count=0, es_count=0),
        storage_exists={"original": True, "converted": False, "bbox": False, "preview": False},
    )
    monkeypatch.setattr(operations, "_snapshot_source", AsyncMock(return_value=snapshot))

    def fake_copy_normal(
        source_file,
        source_space,
        target_space,
        owner_id,
        *,
        target_level,
        target_file_level_path,
    ):
        assert source_file is source
        assert source_space.id == 10
        assert target_space.id == 20
        assert owner_id == 30
        assert target_level == target.level
        assert target_file_level_path == target.file_level_path
        return copied

    monkeypatch.setattr(script_mod, "copy_normal", fake_copy_normal)
    monkeypatch.setattr(script_mod, "_target_preview_object_name", lambda *_args: "")
    monkeypatch.setattr(
        script_mod.KnowledgeFileDao,
        "async_update",
        AsyncMock(side_effect=lambda record: record),
    )

    result = await operations.copy_file(source, target)

    assert result.user_id == 30
    assert result.user_name == "target-owner"
    assert result.updater_id == 30
    assert result.updater_name == "target-owner"


async def test_copy_tags_replaces_target_links_from_cached_source_snapshot(monkeypatch):
    source = _file(101)
    target_file = _file(900, knowledge_id=20)
    target = _target_index().resolve("标准规范", "制度文件").target
    operations = script_mod.BishengMoveOperations(1, {10: _space(10, "source")})
    snapshot = script_mod.SourceSnapshot(
        tags=script_mod.TagSnapshot(approved_ids=(3298,), pending_review_ids=(4401,)),
        permissions=(),
        indexes=script_mod.IndexSnapshot(milvus_count=0, es_count=0),
        storage_exists={},
    )
    operations.snapshots[int(source.id)] = snapshot
    replace_tags = AsyncMock()
    legacy_copy_tags = AsyncMock()
    monkeypatch.setattr(script_mod, "_restore_tag_links", replace_tags)
    monkeypatch.setattr(script_mod, "_copy_file_tags", legacy_copy_tags, raising=False)

    await operations.copy_tags(source, target_file, target)

    replace_tags.assert_awaited_once_with(900, 30, 1, snapshot.tags)
    legacy_copy_tags.assert_not_awaited()


async def test_verify_target_tag_mismatch_reports_source_and_target_ids(monkeypatch):
    source = _file(101)
    target = _target_index().resolve("标准规范", "制度文件").target
    target_file = _file(
        900,
        knowledge_id=int(target.space.id),
        file_level_path=target.file_level_path,
    ).model_copy(update={"user_id": int(target.owner.user_id)})
    operations = script_mod.BishengMoveOperations(1, {10: _space(10, "source")})
    operations.snapshots[int(source.id)] = script_mod.SourceSnapshot(
        tags=script_mod.TagSnapshot(approved_ids=(3298,), pending_review_ids=(4401,)),
        permissions=(),
        indexes=script_mod.IndexSnapshot(milvus_count=0, es_count=0),
        storage_exists={},
    )
    monkeypatch.setattr(script_mod.KnowledgeFileDao, "query_by_id", AsyncMock(return_value=target_file))
    monkeypatch.setattr(script_mod, "_storage_exists", lambda _file: {})
    monkeypatch.setattr(
        script_mod,
        "_index_snapshot",
        lambda _space, _file_id: script_mod.IndexSnapshot(milvus_count=0, es_count=0),
    )
    monkeypatch.setattr(
        script_mod,
        "_tag_snapshot",
        AsyncMock(return_value=script_mod.TagSnapshot(approved_ids=(), pending_review_ids=(4402,))),
    )

    with pytest.raises(RuntimeError) as exc_info:
        await operations.verify_target(source, target_file, target)

    error = str(exc_info.value)
    assert "source=approved=[3298], pending=[4401]" in error
    assert "target=approved=[], pending=[4402]" in error


async def test_delete_overwrite_target_attempts_every_component_and_collects_failures(monkeypatch):
    class EmptySession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def exec(self, _statement):
            return SimpleNamespace(all=lambda: [])

        async def commit(self):
            return None

        async def rollback(self):
            return None

    class Minio:
        bucket = "bucket"

        def __init__(self):
            self.removed = []

        def remove_object_sync(self, *, bucket_name, object_name):
            self.removed.append((bucket_name, object_name))

        def object_exists_sync(self, _bucket, _object_name):
            return False

    minio = Minio()
    monkeypatch.setattr(script_mod, "get_async_db_session", EmptySession)
    monkeypatch.setattr(script_mod, "get_minio_storage_sync", lambda: minio)
    monkeypatch.setattr(script_mod, "delete_vector_files", lambda *_args: True)
    monkeypatch.setattr(
        script_mod,
        "_index_snapshot",
        lambda *_args: script_mod.IndexSnapshot(milvus_count=0, es_count=0),
    )
    monkeypatch.setattr(
        script_mod,
        "_clear_tag_links",
        AsyncMock(side_effect=RuntimeError("tag cleanup failed")),
    )
    monkeypatch.setattr(
        script_mod,
        "_tag_snapshot",
        AsyncMock(return_value=script_mod.TagSnapshot()),
    )
    monkeypatch.setattr(script_mod, "_replace_permission_tuples", AsyncMock())
    monkeypatch.setattr(script_mod, "_read_permission_tuples", AsyncMock(return_value=()))
    delete_file = AsyncMock(return_value=True)
    monkeypatch.setattr(script_mod.KnowledgeFileDao, "adelete_batch", delete_file)
    monkeypatch.setattr(script_mod.KnowledgeFileDao, "query_by_id", AsyncMock(return_value=None))
    monkeypatch.setattr(
        script_mod.KnowledgeDao,
        "async_update_knowledge_update_time_by_id",
        AsyncMock(),
    )
    existing = _file(700, knowledge_id=20, file_name="old.pdf", file_level_path="/200")
    overwrite = script_mod.OverwriteTarget(logical_id="file:700", files=(existing,))
    target = _target_index().resolve("标准规范", "制度文件").target
    operations = script_mod.BishengMoveOperations(1, {10: _space(10, "source")})

    steps = await operations.delete_overwrite_target(overwrite, target)

    assert [step.component for step in steps] == [
        "indexes",
        "objects",
        "tags",
        "permissions",
        "associations",
        "version_graph",
        "database_record",
    ]
    assert next(step for step in steps if step.component == "tags").status == "failed"
    assert all(step.status == "success" for step in steps if step.component != "tags")
    delete_file.assert_awaited_once_with([700])
    assert minio.removed


async def test_revalidate_overwrite_target_rejects_changed_file(monkeypatch):
    expected = _file(700, knowledge_id=20, file_name="old.pdf", file_level_path="/200", md5="old")
    changed = expected.model_copy(update={"md5": "changed"})

    class Session:
        def __init__(self):
            self.results = iter(
                [
                    SimpleNamespace(all=lambda: [changed]),
                    SimpleNamespace(all=lambda: []),
                ]
            )

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def exec(self, _statement):
            return next(self.results)

    monkeypatch.setattr(script_mod, "get_async_db_session", Session)
    operations = script_mod.BishengMoveOperations(1, {10: _space(10, "source")})
    target = _target_index().resolve("标准规范", "制度文件").target

    with pytest.raises(script_mod.OverwritePreconditionError, match="changed after planning"):
        await operations.revalidate_overwrite_target(
            script_mod.OverwriteTarget(logical_id="file:700", files=(expected,)),
            target,
        )


class _FakeMoveOperations:
    def __init__(self, *, fail_at: str | None = None, fail_source_id: int | None = None) -> None:
        self.fail_at = fail_at
        self.fail_source_id = fail_source_id
        self.calls: list[str] = []
        self.next_target_id = 900
        self.target_source_ids: dict[int, int] = {}
        self.source_spaces = {10: _space(10, "source")}
        self.snapshots: dict[int, script_mod.SourceSnapshot] = {}
        self.target_files_by_source_id: dict[int, KnowledgeFile] = {}

    async def snapshot_unit(self, unit):
        self.calls.append(f"snapshot:{unit.unit_id}")
        for source_file in unit.source_files:
            self.snapshots[int(source_file.id)] = script_mod.SourceSnapshot(
                tags=script_mod.TagSnapshot(),
                permissions=(),
                indexes=script_mod.IndexSnapshot(milvus_count=0, es_count=0),
                storage_exists={"original": True, "converted": False, "bbox": False, "preview": False},
            )

    async def copy_file(self, source_file, target):
        self.calls.append(f"copy:{source_file.id}")
        if self.fail_at == "copy" and self.fail_source_id == source_file.id:
            raise RuntimeError("copy failed")
        target_file = _file(
            self.next_target_id,
            knowledge_id=target.space.id,
            file_name=source_file.file_name,
            file_level_path=target.file_level_path,
        )
        self.next_target_id += 1
        self.target_source_ids[int(target_file.id)] = int(source_file.id)
        self.target_files_by_source_id[int(source_file.id)] = target_file
        if self.fail_at == "partial_copy" and self.fail_source_id == source_file.id:
            raise script_mod.TargetCopyError("copy failed after target creation", target_file)
        return target_file

    async def copy_tags(self, source_file, target_file, target):
        self.calls.append(f"tags:{source_file.id}")
        if self.fail_at == "tags" and self.fail_source_id == source_file.id:
            raise RuntimeError("tags failed")

    async def write_permissions(self, target_file, target):
        self.calls.append(f"permissions:{target_file.id}")
        if self.fail_at == "permissions" and self.fail_source_id == self.target_source_ids[int(target_file.id)]:
            raise RuntimeError("permissions failed")

    async def verify_target(self, source_file, target_file, target):
        self.calls.append(f"verify:{source_file.id}")
        if self.fail_at == "verify" and self.fail_source_id == source_file.id:
            raise RuntimeError("verification failed")

    async def delete_source(self, source_file, target_file, target):
        self.calls.append(f"delete:{source_file.id}")
        if self.fail_at == "delete" and self.fail_source_id == source_file.id:
            raise RuntimeError("delete failed")

    async def restore_source(self, source_file, target_file, target):
        self.calls.append(f"restore:{source_file.id}")
        return []

    async def cleanup_target(self, target_file, target):
        self.calls.append(f"cleanup:{target_file.id}")
        return []


class _FakeVersionGraphStore:
    def __init__(self, *, fail_at: str | None = None) -> None:
        self.fail_at = fail_at
        self.calls: list[str] = []

    async def create_target_graph(self, unit, target_files):
        self.calls.append("create_target_graph")
        if self.fail_at == "create":
            raise RuntimeError("graph create failed")
        self.target_file_ids = [int(file.id) for file in target_files]
        return 800

    def get_target_graph_payload(self, target_document_id):
        return {
            "document": {"id": target_document_id, "primary_version_id": 802},
            "versions": [
                {"id": 801, "knowledge_file_id": self.target_file_ids[0], "version_no": 1, "is_primary": False},
                {"id": 802, "knowledge_file_id": self.target_file_ids[1], "version_no": 2, "is_primary": True},
            ],
        }

    async def verify_target_graph(self, unit, target_document_id, target_files):
        self.calls.append("verify_target_graph")
        if self.fail_at == "verify":
            raise RuntimeError("graph verify failed")

    async def delete_source_graph(self, unit):
        self.calls.append("delete_source_graph")

    async def restore_source_graph(self, unit):
        self.calls.append("restore_source_graph")
        return []

    async def delete_target_graph(self, target_document_id):
        self.calls.append("delete_target_graph")
        return []


def _version_unit():
    files = (_file(101), _file(102))
    versions = (
        KnowledgeDocumentVersion(id=701, document_id=500, knowledge_file_id=101, version_no=1, is_primary=False),
        KnowledgeDocumentVersion(id=702, document_id=500, knowledge_file_id=102, version_no=2, is_primary=True),
    )
    target = _target_index().resolve("标准规范", "制度文件").target
    return script_mod.MigrationUnit(
        unit_id="document:500",
        unit_type="version_chain",
        source_files=files,
        target=target,
        category_code="STD",
        category_label="标准规范",
        subcategory_code="STD-A",
        subcategory_label="制度文件",
        source_document=KnowledgeDocument(id=500, knowledge_id=10, primary_version_id=702),
        source_versions=versions,
    )


async def test_move_one_file_verifies_before_deleting_source():
    operations = _FakeMoveOperations()
    source = _file(101)
    target = _target_index().resolve("标准规范", "制度文件").target

    result = await script_mod.move_one_file(source, target, operations)

    assert result.status == "success"
    assert result.target_file_id == 900
    assert result.source_deleted is True
    assert operations.calls == ["copy:101", "tags:101", "permissions:900", "verify:101", "delete:101"]


async def test_move_one_file_runs_overwrite_after_verification_and_continues_on_cleanup_warning():
    operations = _FakeMoveOperations()
    source = _file(101)
    target = _target_index().resolve("标准规范", "制度文件").target

    async def overwrite():
        operations.calls.append("overwrite")
        return ["objects: RuntimeError: old object remains"]

    result = await script_mod.move_one_file(
        source,
        target,
        operations,
        before_source_delete=overwrite,
    )

    assert result.status == "success"
    assert result.reason_code == "overwrite_cleanup_failed"
    assert result.overwrite_cleanup_errors == ["objects: RuntimeError: old object remains"]
    assert operations.calls == [
        "copy:101",
        "tags:101",
        "permissions:900",
        "verify:101",
        "overwrite",
        "delete:101",
    ]


async def test_move_one_file_keeps_source_when_overwrite_precondition_fails():
    operations = _FakeMoveOperations()
    target = _target_index().resolve("标准规范", "制度文件").target

    async def overwrite():
        raise script_mod.OverwritePreconditionError("old target changed")

    result = await script_mod.move_one_file(
        _file(101),
        target,
        operations,
        before_source_delete=overwrite,
    )

    assert result.status == "failed"
    assert "old target changed" in result.error
    assert "delete:101" not in operations.calls
    assert operations.calls[-1] == "cleanup:900"


async def test_move_one_file_cleans_target_and_keeps_source_when_verification_fails():
    operations = _FakeMoveOperations(fail_at="verify", fail_source_id=101)
    target = _target_index().resolve("标准规范", "制度文件").target

    result = await script_mod.move_one_file(_file(101), target, operations)

    assert result.status == "failed"
    assert result.source_deleted is False
    assert result.target_cleanup_succeeded is True
    assert "verification failed" in result.error
    assert operations.calls[-1] == "cleanup:900"


async def test_version_chain_saga_rebuilds_graph_before_deleting_sources():
    operations = _FakeMoveOperations()
    graph_store = _FakeVersionGraphStore()

    results = await script_mod.move_version_chain(_version_unit(), operations, graph_store)

    assert [result.status for result in results] == ["success", "success"]
    assert [result.target_file_id for result in results] == [900, 901]
    assert all(result.target_document_id == 800 for result in results)
    assert [result.target_version_id for result in results] == [801, 802]
    assert graph_store.calls == ["create_target_graph", "verify_target_graph", "delete_source_graph"]
    assert operations.calls.index("verify:102") < operations.calls.index("delete:101")


async def test_version_chain_runs_overwrite_once_before_deleting_source_graph():
    operations = _FakeMoveOperations()
    graph_store = _FakeVersionGraphStore()

    async def overwrite():
        operations.calls.append("overwrite")
        return ["indexes: RuntimeError: old vectors remain"]

    results = await script_mod.move_version_chain(
        _version_unit(),
        operations,
        graph_store,
        before_source_delete=overwrite,
    )

    assert [result.status for result in results] == ["success", "success"]
    assert all(result.reason_code == "overwrite_cleanup_failed" for result in results)
    assert operations.calls.count("overwrite") == 1
    assert operations.calls.index("verify:102") < operations.calls.index("overwrite")
    assert operations.calls.index("overwrite") < operations.calls.index("delete:101")


async def test_version_chain_saga_cleans_all_targets_when_copy_phase_fails():
    operations = _FakeMoveOperations(fail_at="copy", fail_source_id=102)
    graph_store = _FakeVersionGraphStore()

    results = await script_mod.move_version_chain(_version_unit(), operations, graph_store)

    assert [result.status for result in results] == ["failed", "failed"]
    assert "delete_source_graph" not in graph_store.calls
    assert "cleanup:900" in operations.calls
    assert not any(call.startswith("delete:") for call in operations.calls)


async def test_version_chain_saga_cleans_partial_target_reported_by_copy_error():
    operations = _FakeMoveOperations(fail_at="partial_copy", fail_source_id=102)
    graph_store = _FakeVersionGraphStore()

    results = await script_mod.move_version_chain(_version_unit(), operations, graph_store)

    assert [result.status for result in results] == ["failed", "failed"]
    assert [result.target_file_id for result in results] == [900, 901]
    assert "cleanup:900" in operations.calls
    assert "cleanup:901" in operations.calls
    assert not any(call.startswith("delete:") for call in operations.calls)


@pytest.mark.parametrize(
    ("operations_failure", "graph_failure"),
    [
        ("tags", None),
        ("permissions", None),
        ("verify", None),
        (None, "create"),
        (None, "verify"),
    ],
)
async def test_version_chain_saga_compensates_each_pre_delete_failure(
    operations_failure: str | None,
    graph_failure: str | None,
):
    operations = _FakeMoveOperations(fail_at=operations_failure, fail_source_id=102)
    graph_store = _FakeVersionGraphStore(fail_at=graph_failure)

    results = await script_mod.move_version_chain(_version_unit(), operations, graph_store)

    assert [result.status for result in results] == ["failed", "failed"]
    assert not any(call.startswith("delete:") for call in operations.calls)
    assert "cleanup:900" in operations.calls
    assert "cleanup:901" in operations.calls
    if graph_failure == "verify":
        assert "delete_target_graph" in graph_store.calls


async def test_version_chain_saga_restores_source_graph_and_files_when_source_delete_fails():
    operations = _FakeMoveOperations(fail_at="delete", fail_source_id=102)
    graph_store = _FakeVersionGraphStore()

    results = await script_mod.move_version_chain(_version_unit(), operations, graph_store)

    assert [result.status for result in results] == ["failed", "failed"]
    assert graph_store.calls == [
        "create_target_graph",
        "verify_target_graph",
        "delete_source_graph",
        "restore_source_graph",
        "delete_target_graph",
    ]
    assert "restore:101" in operations.calls
    assert "restore:102" in operations.calls
    assert "cleanup:900" in operations.calls
    assert "cleanup:901" in operations.calls


def test_write_json_report_contains_version_traceability(tmp_path):
    report = script_mod.MoveRunReport(
        mode="apply",
        run_id="run-1",
        parameters={"source_space_ids": [10, 11]},
        tenant_id=1,
        scanned_file_count=4,
        source_selected_file_count=3,
        ready_to_move_file_count=2,
        preflight_skipped_file_count=1,
        skip_reasons={"target_name_conflict": 1},
        results=[
            script_mod.FileMoveResult(
                source_file_id=101,
                source_space_id=10,
                source_file_name="doc.pdf",
                status="success",
                unit_id="document:500",
                unit_type="version_chain",
                source_document_id=500,
                target_document_id=800,
                version_no=1,
                target_space_id=20,
                target_folder_id=200,
                target_file_id=900,
                source_deleted=True,
            )
        ],
    )

    output = script_mod.write_json_report(report, tmp_path)
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert payload["summary"] == {
        "failed": 0,
        "overwrite_cleanup_failed": 0,
        "overwrite_documents": 0,
        "overwrite_files": 0,
        "overwrite_units": 0,
        "ready_to_move": 2,
        "scanned": 4,
        "skip_reasons": {"target_name_conflict": 1},
        "skipped": 1,
        "source_selected": 3,
        "success": 1,
    }
    assert payload["results"][0]["unit_type"] == "version_chain"
    assert payload["results"][0]["source_document_id"] == 500
    assert payload["results"][0]["target_document_id"] == 800


def test_planned_overwrite_report_contains_target_details_and_summary(tmp_path):
    source = _file(101, file_name="incoming.pdf", md5="same-md5")
    existing = _file(
        900,
        knowledge_id=20,
        file_name="existing.pdf",
        file_level_path="/200",
        md5="same-md5",
    )
    target = _target_index().resolve("标准规范", "制度文件").target
    unit = script_mod.MigrationUnit(
        unit_id="file:101",
        unit_type="file",
        source_files=(source,),
        target=target,
        category_code="STD",
        category_label="标准规范",
        subcategory_code="STD-A",
        subcategory_label="制度文件",
        overwrite_target=script_mod.OverwriteTarget(
            logical_id="file:900",
            files=(existing,),
            matched_file_ids=(900,),
            match_reasons=("md5",),
        ),
    )
    plan = script_mod.MigrationPlan(
        tenant_id=1,
        source_spaces={10: _space(10, "source")},
        selected_units=[unit],
        skipped_files=[],
    )
    overwrites = script_mod._planned_overwrite_reports(plan)
    report = script_mod.MoveRunReport(
        mode="dry-run",
        run_id="run-overwrite",
        parameters={"force_overwrite": True},
        tenant_id=1,
        ready_to_move_file_count=1,
        overwrites=overwrites,
    )

    output = script_mod.write_json_report(report, tmp_path)
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert payload["summary"]["overwrite_units"] == 1
    assert payload["summary"]["overwrite_documents"] == 1
    assert payload["summary"]["overwrite_files"] == 1
    assert payload["summary"]["overwrite_cleanup_failed"] == 0
    assert payload["overwrites"][0]["logical_id"] == "file:900"
    assert payload["overwrites"][0]["match_reasons"] == ["md5"]
    assert payload["overwrites"][0]["matched_file_ids"] == [900]
    assert payload["overwrites"][0]["target_files"][0]["record"]["id"] == 900
    assert payload["overwrites"][0]["status"] == "planned"


def test_rollback_journal_exclusively_creates_and_appends_jsonl_events(tmp_path):
    path = tmp_path / "rollback.jsonl"
    journal = script_mod.RollbackJournal(path=path, run_id="run-1")
    journal.open()
    journal.append_event(
        "run_started",
        {"started_at": datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)},
    )
    journal.append_event("unit_succeeded", {"unit_id": "file:101"})
    journal.flush()
    journal.close()

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [row["event_type"] for row in rows] == ["run_started", "unit_succeeded"]
    assert [row["sequence"] for row in rows] == [1, 2]
    assert all(row["schema_version"] == 1 and row["run_id"] == "run-1" for row in rows)
    assert rows[0]["payload"]["started_at"] == "2026-07-19T12:00:00+00:00"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600

    with pytest.raises(script_mod.RollbackRecordError, match="already exists"):
        script_mod.RollbackJournal(path=path, run_id="run-2").open()


def test_resolve_rollback_record_path_uses_explicit_path_or_report_directory(tmp_path):
    explicit = tmp_path / "explicit.jsonl"
    assert (
        script_mod.resolve_rollback_record_path(
            SimpleNamespace(rollback_record_file=explicit, report_dir=tmp_path),
            "run-1",
        )
        == explicit
    )
    assert (
        script_mod.resolve_rollback_record_path(
            SimpleNamespace(rollback_record_file=None, report_dir=tmp_path),
            "run-2",
        )
        == tmp_path / "knowledge-file-move-rollback-run-2.jsonl"
    )


def test_rollback_payload_contains_full_source_and_target_traceability():
    source = _file(101, file_level_path="/55")
    target_context = _target_index().resolve("标准规范", "制度文件").target
    unit = script_mod.MigrationUnit(
        unit_id="file:101",
        unit_type="file",
        source_files=(source,),
        target=target_context,
        category_code="STD",
        category_label="标准规范",
        subcategory_code="STD-A",
        subcategory_label="制度文件",
    )
    operations = script_mod.BishengMoveOperations(1, {10: _space(10, "source")})
    operations.snapshots[101] = script_mod.SourceSnapshot(
        tags=script_mod.TagSnapshot(approved_ids=(7,), pending_review_ids=(8,)),
        permissions=({"user": "user:1", "relation": "owner", "object": "knowledge_file:101"},),
        indexes=script_mod.IndexSnapshot(milvus_count=12, es_count=11),
        storage_exists={"original": True, "converted": True, "bbox": False, "preview": True},
    )
    target_file = _file(900, knowledge_id=20, file_level_path="/200")
    operations.target_files_by_source_id[101] = target_file
    result = script_mod.FileMoveResult(
        source_file_id=101,
        source_space_id=10,
        source_file_name="doc.pdf",
        status="success",
        target_space_id=20,
        target_folder_id=200,
        target_file_id=900,
        source_deleted=True,
    )

    started = script_mod.build_unit_started_payload(unit, operations)
    succeeded = script_mod.build_unit_succeeded_payload(unit, [result], operations, target_graph=None)

    source_payload = started["source_files"][0]
    assert source_payload["record"]["id"] == 101
    assert source_payload["source_space"]["id"] == 10
    assert source_payload["source_folder_id"] == 55
    assert source_payload["snapshot"]["tags"]["approved_ids"] == (7,)
    assert source_payload["snapshot"]["permissions"][0]["relation"] == "owner"
    assert source_payload["snapshot"]["indexes"] == {"milvus_count": 12, "es_count": 11}
    assert source_payload["storage_object_names"]["original"] == source.object_name
    assert succeeded["target_files"][0]["record"]["id"] == 900
    assert succeeded["target_files"][0]["source_file_id"] == 101
    assert succeeded["results"][0]["source_deleted"] is True


async def test_run_defaults_to_dry_run_without_constructing_write_operations(monkeypatch, tmp_path, capsys):
    args = script_mod.parse_args(
        [
            "--source-space-id",
            "10",
            "--report-dir",
            str(tmp_path),
        ]
    )
    plan = script_mod.MigrationPlan(
        tenant_id=1,
        source_spaces={10: _space(10, "source")},
        selected_units=[
            script_mod.MigrationUnit(
                unit_id="file:101",
                unit_type="file",
                source_files=(_file(101),),
                target=_target_index().resolve("标准规范", "制度文件").target,
                category_code="STD",
                category_label="标准规范",
                subcategory_code="STD-A",
                subcategory_label="制度文件",
            )
        ],
        skipped_files=[
            script_mod.SkippedFile(
                source_file_id=102,
                source_space_id=10,
                source_file_name="conflict.pdf",
                reason_code="target_name_conflict",
                reason="target folder contains the same file name",
            )
        ],
        scanned_file_count=3,
        source_selected_file_count=2,
    )
    initialize = AsyncMock()
    close = AsyncMock()
    monkeypatch.setattr(script_mod, "initialize_app_context", initialize)
    monkeypatch.setattr(script_mod, "close_app_context", close)
    monkeypatch.setattr(script_mod, "build_migration_plan", AsyncMock(return_value=plan))

    def fail_if_constructed(*_args, **_kwargs):
        raise AssertionError("dry-run must not construct write operations")

    monkeypatch.setattr(script_mod, "BishengMoveOperations", fail_if_constructed)

    assert await script_mod.run(args) == script_mod.EXIT_OK
    assert initialize.await_count == 1
    assert close.await_count == 1
    reports = list(tmp_path.glob("knowledge-file-move-*.json"))
    assert len(reports) == 1
    payload = json.loads(reports[0].read_text(encoding="utf-8"))
    assert payload["mode"] == "dry-run"
    assert len(payload["results"]) == 1
    assert payload["results"][0]["source_file_id"] == 101
    assert payload["results"][0]["status"] == "ready"
    assert payload["results"][0]["reason_code"] == ""
    assert payload["summary"] == {
        "failed": 0,
        "overwrite_cleanup_failed": 0,
        "overwrite_documents": 0,
        "overwrite_files": 0,
        "overwrite_units": 0,
        "ready_to_move": 1,
        "scanned": 3,
        "skip_reasons": {"target_name_conflict": 1},
        "skipped": 1,
        "source_selected": 2,
        "success": 0,
    }
    stdout = capsys.readouterr().out
    assert "[SKIPPED]" not in stdout
    assert (
        "Summary: scanned=3 source_selected=2 ready_to_move=1 skipped=1 success=0 failed=0 "
        "overwrite_units=0 overwrite_documents=0 overwrite_files=0 overwrite_cleanup_failed=0 "
        'skip_reasons={"target_name_conflict": 1}'
    ) in stdout


async def test_run_returns_input_error_before_writes_when_preflight_fails(monkeypatch, tmp_path):
    args = script_mod.parse_args(["--source-space-id", "999", "--report-dir", str(tmp_path)])
    monkeypatch.setattr(script_mod, "initialize_app_context", AsyncMock())
    close = AsyncMock()
    monkeypatch.setattr(script_mod, "close_app_context", close)
    monkeypatch.setattr(
        script_mod,
        "build_migration_plan",
        AsyncMock(side_effect=script_mod.PreflightError("source knowledge spaces not found")),
    )

    def fail_if_constructed(*_args, **_kwargs):
        raise AssertionError("preflight failure must not construct write operations")

    monkeypatch.setattr(script_mod, "BishengMoveOperations", fail_if_constructed)

    assert await script_mod.run(args) == script_mod.EXIT_INPUT_ERROR
    assert close.await_count == 1
    assert not list(tmp_path.glob("knowledge-file-move-*.json"))


async def test_apply_returns_nonzero_when_any_migration_unit_fails(monkeypatch, tmp_path):
    args = script_mod.parse_args(["--source-space-id", "10", "--report-dir", str(tmp_path), "--apply"])
    target = _target_index().resolve("标准规范", "制度文件").target
    plan = script_mod.MigrationPlan(
        tenant_id=1,
        source_spaces={10: _space(10, "source")},
        selected_units=[
            script_mod.MigrationUnit(
                unit_id="file:101",
                unit_type="file",
                source_files=(_file(101),),
                target=target,
                category_code="STD",
                category_label="标准规范",
                subcategory_code="STD-A",
                subcategory_label="制度文件",
            )
        ],
        skipped_files=[
            script_mod.SkippedFile(
                source_file_id=102,
                source_space_id=10,
                source_file_name="conflict.pdf",
                reason_code="target_name_conflict",
                reason="target folder contains the same file name",
            )
        ],
        scanned_file_count=3,
        source_selected_file_count=2,
    )
    failed_result = script_mod.FileMoveResult(
        source_file_id=101,
        source_space_id=10,
        source_file_name="doc.pdf",
        status="failed",
        error="verification failed",
    )
    monkeypatch.setattr(script_mod, "initialize_app_context", AsyncMock())
    monkeypatch.setattr(script_mod, "close_app_context", AsyncMock())
    monkeypatch.setattr(script_mod, "build_migration_plan", AsyncMock(return_value=plan))
    monkeypatch.setattr(script_mod, "BishengMoveOperations", lambda *_args: object())
    monkeypatch.setattr(script_mod, "move_one_file", AsyncMock(return_value=failed_result))

    assert await script_mod.run(args) == script_mod.EXIT_APPLY_ERROR
    payload = json.loads(next(tmp_path.glob("knowledge-file-move-*.json")).read_text(encoding="utf-8"))
    assert [result["source_file_id"] for result in payload["results"]] == [101]
    assert payload["summary"] == {
        "failed": 1,
        "overwrite_cleanup_failed": 0,
        "overwrite_documents": 0,
        "overwrite_files": 0,
        "overwrite_units": 0,
        "ready_to_move": 1,
        "scanned": 3,
        "skip_reasons": {"target_name_conflict": 1},
        "skipped": 1,
        "source_selected": 2,
        "success": 0,
    }


def _single_file_plan(*file_ids: int):
    target = _target_index().resolve("标准规范", "制度文件").target
    return script_mod.MigrationPlan(
        tenant_id=1,
        source_spaces={10: _space(10, "source")},
        selected_units=[
            script_mod.MigrationUnit(
                unit_id=f"file:{file_id}",
                unit_type="file",
                source_files=(_file(file_id, file_name=f"doc-{file_id}.pdf"),),
                target=target,
                category_code="STD",
                category_label="标准规范",
                subcategory_code="STD-A",
                subcategory_label="制度文件",
            )
            for file_id in file_ids
        ],
        skipped_files=[],
    )


def _single_file_overwrite_plan():
    plan = _single_file_plan(101)
    existing = _file(
        700,
        knowledge_id=20,
        file_name="old.pdf",
        file_level_path="/200",
        md5="old-md5",
    )
    plan.selected_units[0] = script_mod.replace(
        plan.selected_units[0],
        overwrite_target=script_mod.OverwriteTarget(
            logical_id="file:700",
            files=(existing,),
            matched_file_ids=(700,),
            match_reasons=("md5",),
        ),
    )
    return plan


class _OverwriteAwareMoveOperations(_FakeMoveOperations):
    def __init__(self, report_dir: Path, *, fail_cleanup: bool = False):
        super().__init__()
        self.report_dir = report_dir
        self.fail_cleanup = fail_cleanup

    async def revalidate_overwrite_target(self, overwrite, target):
        self.calls.append(f"overwrite-revalidate:{overwrite.logical_id}")

    async def snapshot_overwrite_target(self, overwrite, target):
        self.calls.append(f"overwrite-snapshot:{overwrite.logical_id}")
        return [
            {
                "record": overwrite.files[0].model_dump(mode="json"),
                "storage_object_names": [overwrite.files[0].object_name],
                "storage_exists": {"original": True},
                "indexes": {"milvus_count": 1, "es_count": 1},
                "tags": {"approved_ids": [], "pending_review_ids": []},
                "permissions": [],
            }
        ]

    async def delete_overwrite_target(self, overwrite, target):
        rows = [
            json.loads(line)
            for line in next(self.report_dir.glob("knowledge-file-move-rollback-*.jsonl"))
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        assert rows[-1]["event_type"] == "overwrite_started"
        self.calls.append(f"overwrite-delete:{overwrite.logical_id}")
        if self.fail_cleanup:
            return [
                script_mod.OverwriteDeletionStep(
                    component="objects",
                    status="failed",
                    target_file_id=700,
                    error="RuntimeError: object remains",
                )
            ]
        return [
            script_mod.OverwriteDeletionStep(
                component="objects",
                status="success",
                target_file_id=700,
            )
        ]


async def test_apply_flushes_overwrite_lifecycle_before_source_delete(monkeypatch, tmp_path):
    args = script_mod.parse_args(
        [
            "--source-space-id",
            "10",
            "--target-space-id",
            "20",
            "--target-folder-id",
            "200",
            "--force-overwrite",
            "--report-dir",
            str(tmp_path),
            "--apply",
        ]
    )
    operations = _OverwriteAwareMoveOperations(tmp_path)
    monkeypatch.setattr(script_mod, "initialize_app_context", AsyncMock())
    monkeypatch.setattr(script_mod, "close_app_context", AsyncMock())
    monkeypatch.setattr(
        script_mod,
        "build_migration_plan",
        AsyncMock(return_value=_single_file_overwrite_plan()),
    )
    monkeypatch.setattr(script_mod, "BishengMoveOperations", lambda *_args: operations)
    monkeypatch.setattr(script_mod, "DatabaseVersionGraphStore", _FakeVersionGraphStore)

    assert await script_mod.run(args, install_signal_handlers=False) == script_mod.EXIT_OK

    assert operations.calls.index("verify:101") < operations.calls.index("overwrite-delete:file:700")
    assert operations.calls.index("overwrite-delete:file:700") < operations.calls.index("delete:101")
    rows = [
        json.loads(line)
        for line in next(tmp_path.glob("knowledge-file-move-rollback-*.jsonl")).read_text(encoding="utf-8").splitlines()
    ]
    assert [row["event_type"] for row in rows] == [
        "run_started",
        "unit_started",
        "overwrite_started",
        "overwrite_finished",
        "unit_succeeded",
        "run_completed",
    ]


async def test_apply_returns_nonzero_when_overwrite_cleanup_is_partial(monkeypatch, tmp_path):
    args = script_mod.parse_args(
        [
            "--source-space-id",
            "10",
            "--target-space-id",
            "20",
            "--target-folder-id",
            "200",
            "--force-overwrite",
            "--report-dir",
            str(tmp_path),
            "--apply",
        ]
    )
    operations = _OverwriteAwareMoveOperations(tmp_path, fail_cleanup=True)
    monkeypatch.setattr(script_mod, "initialize_app_context", AsyncMock())
    monkeypatch.setattr(script_mod, "close_app_context", AsyncMock())
    monkeypatch.setattr(
        script_mod,
        "build_migration_plan",
        AsyncMock(return_value=_single_file_overwrite_plan()),
    )
    monkeypatch.setattr(script_mod, "BishengMoveOperations", lambda *_args: operations)
    monkeypatch.setattr(script_mod, "DatabaseVersionGraphStore", _FakeVersionGraphStore)

    assert await script_mod.run(args, install_signal_handlers=False) == script_mod.EXIT_APPLY_ERROR

    payload = json.loads(next(tmp_path.glob("knowledge-file-move-*.json")).read_text(encoding="utf-8"))
    assert payload["run_status"] == "completed_with_warnings"
    assert payload["summary"]["success"] == 1
    assert payload["summary"]["failed"] == 0
    assert payload["summary"]["overwrite_cleanup_failed"] == 1
    assert payload["results"][0]["reason_code"] == "overwrite_cleanup_failed"
    assert payload["overwrites"][0]["status"] == "cleanup_failed"
    rows = [
        json.loads(line)
        for line in next(tmp_path.glob("knowledge-file-move-rollback-*.jsonl")).read_text(encoding="utf-8").splitlines()
    ]
    assert rows[-1]["event_type"] == "run_completed_with_warnings"


class _FolderAwareMoveOperations(_FakeMoveOperations):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.folder_mappings: dict[str, tuple[script_mod.FolderMapping, ...]] = {}
        self.folder_cleanup_calls: list[str] = []
        self.copy_target_paths: list[str] = []

    async def prepare_unit_target(self, unit):
        self.calls.append(f"prepare:{unit.unit_id}")
        folder_b = _folder(301, 20, "B", path="/200/300", level=2)
        self.folder_mappings[unit.unit_id] = (
            script_mod.FolderMapping(201, "A", "/201", 300, "A", "/200", "/200/300", 1, "created"),
            script_mod.FolderMapping(
                202,
                "B",
                "/201/202",
                301,
                "B",
                "/200/300",
                "/200/300/301",
                2,
                "created",
            ),
        )
        target = script_mod.TargetContext(
            tenant_id=unit.target.tenant_id,
            space=unit.target.space,
            folder=folder_b,
            owner=unit.target.owner,
            file_level_path="/200/300/301",
            level=3,
        )
        return script_mod.replace(unit, target=target)

    def get_unit_folder_mappings(self, unit_id):
        return self.folder_mappings.get(unit_id, ())

    async def cleanup_unit_folders(self, unit_id):
        self.folder_cleanup_calls.append(unit_id)
        return []

    def release_unit_folders(self, unit_id):
        self.folder_mappings.pop(unit_id, None)

    async def copy_file(self, source_file, target):
        self.copy_target_paths.append(target.file_level_path)
        return await super().copy_file(source_file, target)


def _preserved_folder_plan():
    unit = _folder_structure_unit()
    return script_mod.MigrationPlan(
        tenant_id=1,
        source_spaces={10: _space(10, "source")},
        selected_units=[unit],
        skipped_files=[],
    )


async def test_apply_prepares_preserved_folders_before_copy_and_records_mapping(monkeypatch, tmp_path):
    args = script_mod.parse_args(
        [
            "--source-space-id",
            "10",
            "--preserve-folder-structure",
            "--report-dir",
            str(tmp_path),
            "--apply",
        ]
    )
    operations = _FolderAwareMoveOperations()
    monkeypatch.setattr(script_mod, "initialize_app_context", AsyncMock())
    monkeypatch.setattr(script_mod, "close_app_context", AsyncMock())
    monkeypatch.setattr(script_mod, "build_migration_plan", AsyncMock(return_value=_preserved_folder_plan()))
    monkeypatch.setattr(script_mod, "BishengMoveOperations", lambda *_args: operations)
    monkeypatch.setattr(script_mod, "DatabaseVersionGraphStore", _FakeVersionGraphStore)

    assert await script_mod.run(args, install_signal_handlers=False) == script_mod.EXIT_OK

    assert operations.copy_target_paths == ["/200/300/301"]
    rows = [
        json.loads(line)
        for line in next(tmp_path.glob("knowledge-file-move-rollback-*.jsonl")).read_text(encoding="utf-8").splitlines()
    ]
    started = next(row for row in rows if row["event_type"] == "unit_started")
    succeeded = next(row for row in rows if row["event_type"] == "unit_succeeded")
    assert [folder["folder_name"] for folder in started["payload"]["source_folder_chain"]] == ["A", "B"]
    assert [mapping["action"] for mapping in succeeded["payload"]["folder_mappings"]] == [
        "created",
        "created",
    ]
    assert succeeded["payload"]["target"]["folder"]["id"] == 301


async def test_failed_unit_cleans_new_folders_and_records_actual_mapping(monkeypatch, tmp_path):
    args = script_mod.parse_args(
        [
            "--source-space-id",
            "10",
            "--preserve-folder-structure",
            "--report-dir",
            str(tmp_path),
            "--apply",
        ]
    )
    operations = _FolderAwareMoveOperations(fail_at="verify", fail_source_id=101)
    monkeypatch.setattr(script_mod, "initialize_app_context", AsyncMock())
    monkeypatch.setattr(script_mod, "close_app_context", AsyncMock())
    monkeypatch.setattr(script_mod, "build_migration_plan", AsyncMock(return_value=_preserved_folder_plan()))
    monkeypatch.setattr(script_mod, "BishengMoveOperations", lambda *_args: operations)
    monkeypatch.setattr(script_mod, "DatabaseVersionGraphStore", _FakeVersionGraphStore)

    assert await script_mod.run(args, install_signal_handlers=False) == script_mod.EXIT_APPLY_ERROR

    assert operations.folder_cleanup_calls == ["file:101"]
    rows = [
        json.loads(line)
        for line in next(tmp_path.glob("knowledge-file-move-rollback-*.jsonl")).read_text(encoding="utf-8").splitlines()
    ]
    failed = next(row for row in rows if row["event_type"] == "unit_failed")
    assert [mapping["target_folder_id"] for mapping in failed["payload"]["folder_mappings"]] == [300, 301]


async def test_apply_writes_complete_rollback_lifecycle(monkeypatch, tmp_path):
    args = script_mod.parse_args(
        ["--source-space-id", "10", "--report-dir", str(tmp_path), "--batch-size", "10", "--apply"]
    )
    operations = _FakeMoveOperations()
    monkeypatch.setattr(script_mod, "initialize_app_context", AsyncMock())
    monkeypatch.setattr(script_mod, "close_app_context", AsyncMock())
    monkeypatch.setattr(script_mod, "build_migration_plan", AsyncMock(return_value=_single_file_plan(101)))
    monkeypatch.setattr(script_mod, "BishengMoveOperations", lambda *_args: operations)
    monkeypatch.setattr(script_mod, "DatabaseVersionGraphStore", _FakeVersionGraphStore)

    assert await script_mod.run(args, install_signal_handlers=False) == script_mod.EXIT_OK

    rollback_path = next(tmp_path.glob("knowledge-file-move-rollback-*.jsonl"))
    rows = [json.loads(line) for line in rollback_path.read_text(encoding="utf-8").splitlines()]
    assert [row["event_type"] for row in rows] == [
        "run_started",
        "unit_started",
        "unit_succeeded",
        "run_completed",
    ]
    final_report = json.loads(next(tmp_path.glob("knowledge-file-move-*.json")).read_text(encoding="utf-8"))
    assert final_report["run_status"] == "completed"
    assert final_report["rollback_record_path"] == str(rollback_path.resolve())


async def test_apply_preserves_exit_status_when_journal_close_fails(monkeypatch, tmp_path):
    args = script_mod.parse_args(["--source-space-id", "10", "--report-dir", str(tmp_path), "--apply"])
    operations = _FakeMoveOperations()

    class FailingCloseJournal(script_mod.RollbackJournal):
        def close(self, *, flush=True):
            super().close(flush=flush)
            raise script_mod.RollbackRecordError("close failed")

    monkeypatch.setattr(script_mod, "initialize_app_context", AsyncMock())
    monkeypatch.setattr(script_mod, "close_app_context", AsyncMock())
    monkeypatch.setattr(script_mod, "build_migration_plan", AsyncMock(return_value=_single_file_plan(101)))
    monkeypatch.setattr(script_mod, "BishengMoveOperations", lambda *_args: operations)
    monkeypatch.setattr(script_mod, "DatabaseVersionGraphStore", _FakeVersionGraphStore)
    monkeypatch.setattr(script_mod, "RollbackJournal", FailingCloseJournal)

    assert await script_mod.run(args, install_signal_handlers=False) == script_mod.EXIT_OK


async def test_apply_stops_after_first_failed_unit_and_flushes_failure(monkeypatch, tmp_path):
    args = script_mod.parse_args(["--source-space-id", "10", "--report-dir", str(tmp_path), "--apply"])
    operations = _FakeMoveOperations(fail_at="verify", fail_source_id=101)
    monkeypatch.setattr(script_mod, "initialize_app_context", AsyncMock())
    monkeypatch.setattr(script_mod, "close_app_context", AsyncMock())
    monkeypatch.setattr(script_mod, "build_migration_plan", AsyncMock(return_value=_single_file_plan(101, 102)))
    monkeypatch.setattr(script_mod, "BishengMoveOperations", lambda *_args: operations)
    monkeypatch.setattr(script_mod, "DatabaseVersionGraphStore", _FakeVersionGraphStore)

    assert await script_mod.run(args, install_signal_handlers=False) == script_mod.EXIT_APPLY_ERROR

    assert "copy:101" in operations.calls
    assert "copy:102" not in operations.calls
    rows = [
        json.loads(line)
        for line in next(tmp_path.glob("knowledge-file-move-rollback-*.jsonl")).read_text(encoding="utf-8").splitlines()
    ]
    assert [row["event_type"] for row in rows][-2:] == ["unit_failed", "run_failed"]
    final_report = json.loads(next(tmp_path.glob("knowledge-file-move-*.json")).read_text(encoding="utf-8"))
    assert final_report["pending_units"] == 1


async def test_apply_honors_graceful_stop_after_current_unit(monkeypatch, tmp_path):
    args = script_mod.parse_args(["--source-space-id", "10", "--report-dir", str(tmp_path), "--apply"])
    stop_controller = script_mod.StopController()

    class InterruptingOperations(_FakeMoveOperations):
        async def delete_source(self, source_file, target_file, target):
            await super().delete_source(source_file, target_file, target)
            stop_controller.request_stop()

    operations = InterruptingOperations()
    monkeypatch.setattr(script_mod, "initialize_app_context", AsyncMock())
    monkeypatch.setattr(script_mod, "close_app_context", AsyncMock())
    monkeypatch.setattr(script_mod, "build_migration_plan", AsyncMock(return_value=_single_file_plan(101, 102)))
    monkeypatch.setattr(script_mod, "BishengMoveOperations", lambda *_args: operations)
    monkeypatch.setattr(script_mod, "DatabaseVersionGraphStore", _FakeVersionGraphStore)

    assert (
        await script_mod.run(
            args,
            stop_controller=stop_controller,
            install_signal_handlers=False,
        )
        == 130
    )

    assert "copy:101" in operations.calls
    assert "copy:102" not in operations.calls
    rows = [
        json.loads(line)
        for line in next(tmp_path.glob("knowledge-file-move-rollback-*.jsonl")).read_text(encoding="utf-8").splitlines()
    ]
    assert rows[-1]["event_type"] == "run_interrupted"
    final_report = json.loads(next(tmp_path.glob("knowledge-file-move-*.json")).read_text(encoding="utf-8"))
    assert final_report["pending_units"] == 1


async def test_rollback_record_checkpoint_failure_compensates_unpersisted_batch(monkeypatch, tmp_path):
    args = script_mod.parse_args(
        ["--source-space-id", "10", "--report-dir", str(tmp_path), "--batch-size", "1", "--apply"]
    )
    operations = _FakeMoveOperations()

    class FailingCheckpointJournal(script_mod.RollbackJournal):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.flush_calls = 0

        def flush(self):
            self.flush_calls += 1
            if self.flush_calls == 2:
                raise script_mod.RollbackRecordError("checkpoint failed")
            return super().flush()

    monkeypatch.setattr(script_mod, "initialize_app_context", AsyncMock())
    monkeypatch.setattr(script_mod, "close_app_context", AsyncMock())
    monkeypatch.setattr(script_mod, "build_migration_plan", AsyncMock(return_value=_single_file_plan(101, 102)))
    monkeypatch.setattr(script_mod, "BishengMoveOperations", lambda *_args: operations)
    monkeypatch.setattr(script_mod, "DatabaseVersionGraphStore", _FakeVersionGraphStore)
    monkeypatch.setattr(script_mod, "RollbackJournal", FailingCheckpointJournal)

    assert await script_mod.run(args, install_signal_handlers=False) == script_mod.EXIT_APPLY_ERROR

    assert "restore:101" in operations.calls
    assert "cleanup:900" in operations.calls
    assert "copy:102" not in operations.calls
    payload = json.loads(next(tmp_path.glob("knowledge-file-move-*.json")).read_text(encoding="utf-8"))
    moved = next(result for result in payload["results"] if result["source_file_id"] == 101)
    assert moved["status"] == "failed"
    assert moved["source_deleted"] is False
    assert moved["reason_code"] == "rollback_record_write_failed"


async def test_checkpoint_failure_also_cleans_created_target_folders(monkeypatch, tmp_path):
    args = script_mod.parse_args(
        [
            "--source-space-id",
            "10",
            "--preserve-folder-structure",
            "--report-dir",
            str(tmp_path),
            "--batch-size",
            "1",
            "--apply",
        ]
    )
    operations = _FolderAwareMoveOperations()

    class FailingCheckpointJournal(script_mod.RollbackJournal):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.flush_calls = 0

        def flush(self):
            self.flush_calls += 1
            if self.flush_calls == 2:
                raise script_mod.RollbackRecordError("checkpoint failed")
            return super().flush()

    monkeypatch.setattr(script_mod, "initialize_app_context", AsyncMock())
    monkeypatch.setattr(script_mod, "close_app_context", AsyncMock())
    monkeypatch.setattr(script_mod, "build_migration_plan", AsyncMock(return_value=_preserved_folder_plan()))
    monkeypatch.setattr(script_mod, "BishengMoveOperations", lambda *_args: operations)
    monkeypatch.setattr(script_mod, "DatabaseVersionGraphStore", _FakeVersionGraphStore)
    monkeypatch.setattr(script_mod, "RollbackJournal", FailingCheckpointJournal)

    assert await script_mod.run(args, install_signal_handlers=False) == script_mod.EXIT_APPLY_ERROR

    assert "restore:101" in operations.calls
    assert "cleanup:900" in operations.calls
    assert operations.folder_cleanup_calls == ["file:101"]
    payload = json.loads(next(tmp_path.glob("knowledge-file-move-*.json")).read_text(encoding="utf-8"))
    moved = next(result for result in payload["results"] if result["source_file_id"] == 101)
    assert moved["reason_code"] == "rollback_record_write_failed"
    assert [mapping["target_folder_id"] for mapping in moved["folder_mappings"]] == [300, 301]


async def test_apply_rejects_existing_rollback_record_before_write_operations(monkeypatch, tmp_path):
    rollback_path = tmp_path / "existing.jsonl"
    rollback_path.write_text("existing\n", encoding="utf-8")
    args = script_mod.parse_args(
        [
            "--source-space-id",
            "10",
            "--report-dir",
            str(tmp_path),
            "--rollback-record-file",
            str(rollback_path),
            "--apply",
        ]
    )
    monkeypatch.setattr(script_mod, "initialize_app_context", AsyncMock())
    monkeypatch.setattr(script_mod, "close_app_context", AsyncMock())
    monkeypatch.setattr(script_mod, "build_migration_plan", AsyncMock(return_value=_single_file_plan(101)))

    def fail_if_constructed(*_args, **_kwargs):
        raise AssertionError("write operations must not be constructed when the rollback record exists")

    monkeypatch.setattr(script_mod, "BishengMoveOperations", fail_if_constructed)

    assert await script_mod.run(args, install_signal_handlers=False) == script_mod.EXIT_INPUT_ERROR
    assert rollback_path.read_text(encoding="utf-8") == "existing\n"


async def test_batch_size_counts_completed_migration_units(monkeypatch, tmp_path):
    args = script_mod.parse_args(
        ["--source-space-id", "10", "--report-dir", str(tmp_path), "--batch-size", "2", "--apply"]
    )
    operations = _FakeMoveOperations()
    instances = []

    class CountingJournal(script_mod.RollbackJournal):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.flush_calls = 0
            instances.append(self)

        def flush(self):
            self.flush_calls += 1
            return super().flush()

    monkeypatch.setattr(script_mod, "initialize_app_context", AsyncMock())
    monkeypatch.setattr(script_mod, "close_app_context", AsyncMock())
    monkeypatch.setattr(script_mod, "build_migration_plan", AsyncMock(return_value=_single_file_plan(101, 102, 103)))
    monkeypatch.setattr(script_mod, "BishengMoveOperations", lambda *_args: operations)
    monkeypatch.setattr(script_mod, "DatabaseVersionGraphStore", _FakeVersionGraphStore)
    monkeypatch.setattr(script_mod, "RollbackJournal", CountingJournal)

    assert await script_mod.run(args, install_signal_handlers=False) == script_mod.EXIT_OK
    assert instances[0].flush_calls == 3  # run_started, two completed units, final remaining unit
