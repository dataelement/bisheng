"""Tests for the classified public-space knowledge-file move script."""

from __future__ import annotations

import json
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
        assert script_mod._skipped_to_result(item).error == item.reason


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


class _FakeMoveOperations:
    def __init__(self, *, fail_at: str | None = None, fail_source_id: int | None = None) -> None:
        self.fail_at = fail_at
        self.fail_source_id = fail_source_id
        self.calls: list[str] = []
        self.next_target_id = 900
        self.target_source_ids: dict[int, int] = {}

    async def copy_file(self, source_file, target):
        self.calls.append(f"copy:{source_file.id}")
        if self.fail_at == "copy" and self.fail_source_id == source_file.id:
            raise RuntimeError("copy failed")
        target_file = _file(self.next_target_id, knowledge_id=target.space.id, file_name=source_file.file_name)
        self.next_target_id += 1
        self.target_source_ids[int(target_file.id)] = int(source_file.id)
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
        return 800

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
    assert graph_store.calls == ["create_target_graph", "verify_target_graph", "delete_source_graph"]
    assert operations.calls.index("verify:102") < operations.calls.index("delete:101")


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

    assert payload["summary"] == {"failed": 0, "skipped": 0, "success": 1, "total": 1}
    assert payload["results"][0]["unit_type"] == "version_chain"
    assert payload["results"][0]["source_document_id"] == 500
    assert payload["results"][0]["target_document_id"] == 800


async def test_run_defaults_to_dry_run_without_constructing_write_operations(monkeypatch, tmp_path):
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
        skipped_files=[],
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
    assert payload["results"][0]["reason_code"] == "dry_run_selected"


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
        skipped_files=[],
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
    assert payload["summary"]["failed"] == 1
