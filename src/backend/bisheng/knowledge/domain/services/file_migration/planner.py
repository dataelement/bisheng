"""不依赖 ORM、Celery 或外部客户端的迁移选择与预检算法。"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

NodeType = Literal["file", "folder"]
ConflictStrategy = Literal["skip", "overwrite"]


@dataclass(frozen=True)
class MigrationNode:
    node_type: NodeType
    node_id: int
    ancestor_folder_ids: tuple[int, ...] = field(default=(), compare=False)


@dataclass(frozen=True)
class MigrationSelection:
    space_id: int
    nodes: tuple[MigrationNode, ...]


def normalize_selections(selections: Sequence[MigrationSelection]) -> tuple[MigrationSelection, ...]:
    nodes_by_space: dict[int, list[MigrationNode]] = {}
    for selection in selections:
        nodes_by_space.setdefault(selection.space_id, []).extend(
            selection.nodes
        )
    normalized: list[MigrationSelection] = []
    for space_id, nodes in nodes_by_space.items():
        selected_folder_ids = {
            node.node_id for node in nodes if node.node_type == "folder"
        }
        kept: list[MigrationNode] = []
        seen: set[tuple[str, int]] = set()
        for node in nodes:
            key = (node.node_type, node.node_id)
            if key in seen:
                continue
            seen.add(key)
            if selected_folder_ids.intersection(node.ancestor_folder_ids):
                continue
            kept.append(MigrationNode(node.node_type, node.node_id))
        if kept:
            normalized.append(
                MigrationSelection(space_id=space_id, nodes=tuple(kept))
            )
    return tuple(normalized)


def normalize_folder_name(name: str) -> str:
    return unicodedata.normalize("NFKC", name).strip().casefold()


@dataclass(frozen=True)
class ExistingTargetFolder:
    folder_id: int
    parent_id: int | None
    name: str


@dataclass(frozen=True)
class FolderMappingStep:
    name: str
    normalized_name: str
    parent_id: int | None
    folder_id: int | None
    action: Literal["reuse", "create"]


@dataclass(frozen=True)
class FolderMappingPlan:
    target_folder_id: int | None
    steps: tuple[FolderMappingStep, ...]

    @property
    def final_folder_id(self) -> int | None:
        return self.steps[-1].folder_id if self.steps else self.target_folder_id


def build_folder_mapping(
    *,
    target_folder_id: int | None,
    source_chain: Sequence[str],
    preserve_structure: bool,
    existing_folders: Sequence[ExistingTargetFolder],
) -> FolderMappingPlan:
    if not preserve_structure or not source_chain:
        return FolderMappingPlan(target_folder_id=target_folder_id, steps=())

    by_parent_and_name: dict[tuple[int | None, str], list[ExistingTargetFolder]] = {}
    for folder in existing_folders:
        key = (folder.parent_id, normalize_folder_name(folder.name))
        by_parent_and_name.setdefault(key, []).append(folder)

    parent_id = target_folder_id
    steps: list[FolderMappingStep] = []
    for name in source_chain:
        normalized_name = normalize_folder_name(name)
        matches = by_parent_and_name.get((parent_id, normalized_name), [])
        if len(matches) > 1:
            raise ValueError(
                f"ambiguous target folder: parent={parent_id}, normalized_name={normalized_name}"
            )
        if matches:
            folder_id = matches[0].folder_id
            action: Literal["reuse", "create"] = "reuse"
        else:
            folder_id = None
            action = "create"
        steps.append(
            FolderMappingStep(
                name=unicodedata.normalize("NFKC", name).strip(),
                normalized_name=normalized_name,
                parent_id=parent_id,
                folder_id=folder_id,
                action=action,
            )
        )
        parent_id = folder_id
    return FolderMappingPlan(target_folder_id=target_folder_id, steps=tuple(steps))


@dataclass(frozen=True)
class SourceFile:
    file_id: int
    space_id: int
    file_name: str
    status: int
    entry_type: str | None = None
    document_id: int | None = None


@dataclass(frozen=True)
class PlannedUnit:
    unit_key: str
    unit_type: Literal["file", "version_chain"]
    source_file_ids: tuple[int, ...]


@dataclass(frozen=True)
class SkippedSource:
    file_id: int
    reason_code: str
    summary: str


@dataclass(frozen=True)
class SourcePlan:
    units: tuple[PlannedUnit, ...]
    skipped: tuple[SkippedSource, ...]


def plan_source_files(source_files: Sequence[SourceFile]) -> SourcePlan:
    units: list[PlannedUnit] = []
    skipped: list[SkippedSource] = []
    seen_units: set[str] = set()
    for source_file in source_files:
        if source_file.status != 2:
            skipped.append(
                SkippedSource(
                    source_file.file_id,
                    "source_file_not_ready",
                    "来源文件尚未处于 SUCCESS 状态",
                )
            )
            continue
        if source_file.entry_type in {"publish", "share", "projection_tombstone"}:
            skipped.append(
                SkippedSource(
                    source_file.file_id,
                    "source_logic_entry_unsupported",
                    "发布、共享或投影清理入口不参与物理迁移",
                )
            )
            continue
        unit_key = (
            f"document:{source_file.document_id}"
            if source_file.document_id is not None
            else f"file:{source_file.file_id}"
        )
        if unit_key in seen_units:
            continue
        seen_units.add(unit_key)
        units.append(
            PlannedUnit(
                unit_key=unit_key,
                unit_type="version_chain" if source_file.document_id is not None else "file",
                source_file_ids=(source_file.file_id,),
            )
        )
    return SourcePlan(units=tuple(units), skipped=tuple(skipped))


@dataclass(frozen=True)
class ConflictCandidate:
    unit_key: str
    matched_by: tuple[Literal["name", "md5"], ...]
    has_active_distribution: bool = False
    graph_valid: bool = True


@dataclass(frozen=True)
class ConflictResolution:
    overwrite_unit_key: str | None = None
    requires_confirmation: bool = False
    reason_code: str = ""


def resolve_conflict(
    *,
    strategy: ConflictStrategy,
    candidates: Sequence[ConflictCandidate],
) -> ConflictResolution:
    if not candidates:
        return ConflictResolution()
    if strategy == "skip":
        return ConflictResolution(reason_code="target_conflict_skip")
    logical_keys = {candidate.unit_key for candidate in candidates}
    if len(logical_keys) != 1:
        return ConflictResolution(reason_code="target_conflict_ambiguous")
    if any(not candidate.graph_valid for candidate in candidates):
        return ConflictResolution(reason_code="target_version_graph_invalid")
    if any(candidate.has_active_distribution for candidate in candidates):
        return ConflictResolution(reason_code="target_distribution_graph_protected")
    return ConflictResolution(
        overwrite_unit_key=next(iter(logical_keys)),
        requires_confirmation=True,
    )
