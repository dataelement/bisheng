import pytest

from bisheng.knowledge.domain.services.file_migration.planner import (
    ConflictCandidate,
    ExistingTargetFolder,
    MigrationNode,
    MigrationSelection,
    SourceFile,
    build_folder_mapping,
    normalize_folder_name,
    normalize_selections,
    plan_source_files,
    resolve_conflict,
)


def test_selection_normalization_deduplicates_nodes_and_removes_descendants():
    selections = [
        MigrationSelection(
            space_id=1,
            nodes=(
                MigrationNode("folder", 10, ancestor_folder_ids=()),
                MigrationNode("folder", 11, ancestor_folder_ids=(10,)),
                MigrationNode("file", 20, ancestor_folder_ids=(10, 11)),
                MigrationNode("file", 20, ancestor_folder_ids=(10, 11)),
            ),
        ),
        MigrationSelection(
            space_id=1,
            nodes=(MigrationNode("file", 21),),
        ),
        MigrationSelection(space_id=2, nodes=(MigrationNode("file", 30),)),
    ]

    normalized = normalize_selections(selections)

    assert normalized == (
        MigrationSelection(
            space_id=1,
            nodes=(
                MigrationNode("folder", 10),
                MigrationNode("file", 21),
            ),
        ),
        MigrationSelection(space_id=2, nodes=(MigrationNode("file", 30),)),
    )


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("  资料  ", "资料"),
        ("ＡＢＣ", "abc"),  # noqa: RUF001 - 验证 NFKC 全角字符归一化。
        ("Straße", "strasse"),
    ],
)
def test_folder_name_normalization_uses_nfkc_trim_and_casefold(name: str, expected: str):
    assert normalize_folder_name(name) == expected


def test_preserve_structure_includes_selected_root_but_individual_file_stays_at_target():
    existing = [ExistingTargetFolder(folder_id=900, parent_id=100, name="资料")]

    selected_folder_mapping = build_folder_mapping(
        target_folder_id=100,
        source_chain=("  资料 ", "2026"),
        preserve_structure=True,
        existing_folders=existing,
    )
    individual_file_mapping = build_folder_mapping(
        target_folder_id=100,
        source_chain=(),
        preserve_structure=True,
        existing_folders=existing,
    )

    assert selected_folder_mapping.steps[0].folder_id == 900
    assert selected_folder_mapping.steps[0].action == "reuse"
    assert selected_folder_mapping.steps[1].name == "2026"
    assert individual_file_mapping.final_folder_id == 100


def test_planner_accepts_only_success_physical_files_and_skips_logic_entries():
    source_files = [
        SourceFile(file_id=1, space_id=1, file_name="ok.pdf", status=2),
        SourceFile(file_id=2, space_id=1, file_name="bad.pdf", status=3),
        SourceFile(file_id=3, space_id=1, file_name="published", status=2, entry_type="publish"),
        SourceFile(file_id=4, space_id=1, file_name="shared", status=2, entry_type="share"),
        SourceFile(file_id=5, space_id=1, file_name="tombstone", status=2, entry_type="projection_tombstone"),
    ]

    result = plan_source_files(source_files)

    assert [unit.unit_key for unit in result.units] == ["file:1"]
    assert {item.reason_code for item in result.skipped} == {
        "source_file_not_ready",
        "source_logic_entry_unsupported",
    }


def test_overwrite_conflict_fails_closed_for_ambiguous_or_distributed_targets():
    ambiguous = resolve_conflict(
        strategy="overwrite",
        candidates=(
            ConflictCandidate("file:1", matched_by=("name",)),
            ConflictCandidate("file:2", matched_by=("md5",)),
        ),
    )
    protected = resolve_conflict(
        strategy="overwrite",
        candidates=(ConflictCandidate("document:8", matched_by=("name",), has_active_distribution=True),),
    )
    safe = resolve_conflict(
        strategy="overwrite",
        candidates=(ConflictCandidate("document:9", matched_by=("name", "md5")),),
    )

    assert ambiguous.reason_code == "target_conflict_ambiguous"
    assert protected.reason_code == "target_distribution_graph_protected"
    assert safe.overwrite_unit_key == "document:9"
    assert safe.requires_confirmation is True
