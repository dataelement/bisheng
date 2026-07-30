"""异步展开来源选择并持久化不可变迁移计划。"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from bisheng.knowledge.domain.models.knowledge_document import (
    KnowledgeDocumentLifecycleStatus,
)
from bisheng.knowledge.domain.models.knowledge_file import (
    FileType,
    KnowledgeFile,
    KnowledgeFileEntryStatus,
    KnowledgeFileEntryType,
    KnowledgeFileStatus,
)
from bisheng.knowledge.domain.models.knowledge_migration import (
    KnowledgeMigrationBatch,
    KnowledgeMigrationBatchStatus,
    KnowledgeMigrationFile,
    KnowledgeMigrationUnit,
    KnowledgeMigrationUnitStatus,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_migration_preflight_inspector import (
    KnowledgeMigrationPreflightInspector,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_migration_repository import (
    KnowledgeMigrationRepository,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_migration_source_repository import (
    KnowledgeMigrationSourceRepository,
)
from bisheng.knowledge.domain.services.file_migration.planner import (
    ConflictCandidate,
    normalize_folder_name,
    resolve_conflict,
)
from bisheng.knowledge.domain.services.knowledge_migration_service import (
    CeleryKnowledgeMigrationTaskDispatcher,
    KnowledgeMigrationTaskDispatcher,
    sanitize_error_summary,
)


@dataclass(frozen=True)
class _PlannedSourceUnit:
    unit_key: str
    unit_type: str
    files: tuple[KnowledgeFile, ...]
    document_id: int | None = None
    reason_code: str | None = None
    summary: str | None = None


@dataclass(frozen=True)
class _TargetLocation:
    display_path: str
    raw_parent_path: str | None
    folder_id: int | None
    mapping_snapshot: list[dict[str, Any]]
    reason_code: str | None = None


class KnowledgeMigrationPlannerService:
    def __init__(
        self,
        *,
        repository: KnowledgeMigrationRepository,
        source_repository: KnowledgeMigrationSourceRepository,
        preflight_inspector: KnowledgeMigrationPreflightInspector,
        dispatcher: KnowledgeMigrationTaskDispatcher | None = None,
    ):
        self.repository = repository
        self.source_repository = source_repository
        self.preflight_inspector = preflight_inspector
        self.dispatcher = dispatcher or CeleryKnowledgeMigrationTaskDispatcher()

    @staticmethod
    def _skip_unit(
        file: KnowledgeFile,
        reason_code: str,
        summary: str,
    ) -> _PlannedSourceUnit:
        return _PlannedSourceUnit(
            unit_key=f"file:{file.id}",
            unit_type="file",
            files=(file,),
            reason_code=reason_code,
            summary=summary,
        )

    async def _build_source_units(
        self,
        batch: KnowledgeMigrationBatch,
        selected_files: list[KnowledgeFile],
    ) -> tuple[list[_PlannedSourceUnit], dict[int, Any], dict[int, Any]]:
        selected_by_id = {int(file.id): file for file in selected_files}
        version_rows = await self.source_repository.find_versions_by_file_ids(
            set(selected_by_id)
        )
        selected_version_by_file_id = {
            int(version.knowledge_file_id): version for version in version_rows
        }
        document_ids = {int(version.document_id) for version in version_rows}
        documents = {
            int(document.id): document
            for document in await self.source_repository.find_documents_by_ids(document_ids)
        }
        all_versions = await self.source_repository.find_versions_by_document_ids(document_ids)
        versions_by_document: dict[int, list[Any]] = defaultdict(list)
        for version in all_versions:
            versions_by_document[int(version.document_id)].append(version)
        version_file_ids = {
            int(version.knowledge_file_id) for version in all_versions
        }
        all_version_files = {
            int(file.id): file
            for file in await self.source_repository.find_files_by_ids(version_file_ids)
        }

        units: list[_PlannedSourceUnit] = []
        accounted: set[int] = set()
        for file in selected_files:
            file_id = int(file.id)
            if file.entry_type in {
                KnowledgeFileEntryType.PUBLISH.value,
                KnowledgeFileEntryType.SHARE.value,
                KnowledgeFileEntryType.PROJECTION_TOMBSTONE.value,
            }:
                units.append(
                    self._skip_unit(
                        file,
                        "source_logic_entry_unsupported",
                        "发布、共享和投影清理入口不复制",
                    )
                )
                accounted.add(file_id)
            elif file.status != KnowledgeFileStatus.SUCCESS.value:
                units.append(
                    self._skip_unit(
                        file,
                        "source_file_not_ready",
                        "来源文件不是 SUCCESS 状态",
                    )
                )
                accounted.add(file_id)
            elif (
                file.entry_type == KnowledgeFileEntryType.MANAGER.value
                and file.entry_status != KnowledgeFileEntryStatus.ACTIVE.value
            ):
                units.append(
                    self._skip_unit(
                        file,
                        "source_manager_not_active",
                        "manager 入口不是 active 状态",
                    )
                )
                accounted.add(file_id)

        for document_id in sorted(document_ids):
            selected_document_files = {
                file_id
                for file_id, version in selected_version_by_file_id.items()
                if int(version.document_id) == document_id
                and file_id not in accounted
            }
            if not selected_document_files:
                continue
            document = documents.get(document_id)
            versions = sorted(
                versions_by_document.get(document_id, []),
                key=lambda item: (int(item.version_no), int(item.id)),
            )
            chain_file_ids = {int(version.knowledge_file_id) for version in versions}
            chain_files = tuple(
                all_version_files[file_id]
                for file_id in sorted(
                    chain_file_ids,
                    key=lambda value: next(
                        int(item.version_no)
                        for item in versions
                        if int(item.knowledge_file_id) == value
                    ),
                )
                if file_id in all_version_files
            )
            reason_code = None
            summary = None
            version_numbers = [int(version.version_no) for version in versions]
            primary_versions = [version for version in versions if version.is_primary]
            allowed_source_spaces = {
                int(item["id"]) for item in batch.source_spaces_snapshot
            }
            if document is None or document.lifecycle_status != KnowledgeDocumentLifecycleStatus.ACTIVE.value:
                reason_code = "source_document_not_active"
                summary = "canonical document 不存在或不处于 active"
            elif not versions or len(chain_files) != len(versions):
                reason_code = "source_version_graph_invalid"
                summary = "版本物理文件缺失"
            elif len(version_numbers) != len(set(version_numbers)) or any(
                number <= 0 for number in version_numbers
            ):
                reason_code = "source_version_graph_invalid"
                summary = "版本号不是唯一正整数"
            elif len(primary_versions) != 1 or int(document.primary_version_id or 0) != int(
                primary_versions[0].id
            ):
                reason_code = "source_version_graph_invalid"
                summary = "主版本指针不一致"
            elif selected_document_files != chain_file_ids:
                reason_code = "source_version_chain_outside_selection"
                summary = "所选范围没有覆盖完整版本链"
            elif any(
                file.status != KnowledgeFileStatus.SUCCESS.value
                or int(file.knowledge_id) not in allowed_source_spaces
                for file in chain_files
            ):
                reason_code = "source_version_chain_not_ready"
                summary = "版本链包含非 SUCCESS 或来源范围外文件"
            elif batch.preserve_structure and len(
                {file.file_level_path or "" for file in chain_files}
            ) > 1:
                reason_code = "source_version_folder_mismatch"
                summary = "保留目录结构时版本链不在同一来源目录"
            units.append(
                _PlannedSourceUnit(
                    unit_key=f"document:{document_id}",
                    unit_type="version_chain",
                    files=chain_files or tuple(
                        selected_by_id[file_id] for file_id in selected_document_files
                    ),
                    document_id=document_id,
                    reason_code=reason_code,
                    summary=summary,
                )
            )
            accounted.update(selected_document_files)

        for file in selected_files:
            file_id = int(file.id)
            if file_id in accounted:
                continue
            units.append(
                _PlannedSourceUnit(
                    unit_key=f"file:{file_id}",
                    unit_type="file",
                    files=(file,),
                )
            )
            accounted.add(file_id)
        return units, selected_version_by_file_id, documents

    async def _folder_context(
        self,
        batch: KnowledgeMigrationBatch,
        selected_files: list[KnowledgeFile],
    ) -> tuple[dict[int, KnowledgeFile], set[int], set[int]]:
        folder_ids: set[int] = set()
        selected_folder_ids: set[int] = set()
        selected_file_ids: set[int] = set()
        for selection in batch.source_selection_snapshot:
            for node in selection["nodes"]:
                if node["node_type"] == "folder":
                    selected_folder_ids.add(int(node["node_id"]))
                else:
                    selected_file_ids.add(int(node["node_id"]))
        for file in selected_files:
            folder_ids.update(
                int(part)
                for part in (file.file_level_path or "").split("/")
                if part.isdigit()
            )
        folders = {
            int(item.id): item
            for item in await self.source_repository.find_files_by_ids(folder_ids)
            if item.file_type == FileType.DIR.value
        }
        return folders, selected_folder_ids, selected_file_ids

    @staticmethod
    def _source_chain(
        file: KnowledgeFile,
        *,
        preserve_structure: bool,
        selected_folder_ids: set[int],
        selected_file_ids: set[int],
        folders: dict[int, KnowledgeFile],
    ) -> list[KnowledgeFile]:
        if not preserve_structure or int(file.id) in selected_file_ids:
            return []
        path_ids = [
            int(part)
            for part in (file.file_level_path or "").split("/")
            if part.isdigit()
        ]
        selected_indexes = [
            index for index, folder_id in enumerate(path_ids) if folder_id in selected_folder_ids
        ]
        if not selected_indexes:
            return []
        start = min(selected_indexes)
        return [folders[folder_id] for folder_id in path_ids[start:] if folder_id in folders]

    @staticmethod
    def _full_source_chain(
        file: KnowledgeFile,
        folders: dict[int, KnowledgeFile],
    ) -> list[KnowledgeFile]:
        return [
            folders[folder_id]
            for folder_id in (
                int(part)
                for part in (file.file_level_path or "").split("/")
                if part.isdigit()
            )
            if folder_id in folders
        ]

    @staticmethod
    def _resolve_target_location(
        batch: KnowledgeMigrationBatch,
        source_chain: list[KnowledgeFile],
        target_folders: list[KnowledgeFile],
    ) -> _TargetLocation:
        parent_id = batch.target_folder_id
        raw_parent_path: str | None = (
            batch.target_path_snapshot if batch.target_folder_id is not None else ""
        )
        display_parts = [batch.target_folder_name] if batch.target_folder_name else []
        mapping = []
        for folder in source_chain:
            display_parts.append(folder.file_name)
            if raw_parent_path is None:
                mapping.append(
                    {
                        "source_folder_id": int(folder.id),
                        "source_name": folder.file_name,
                        "target_folder_id": None,
                        "action": "planned",
                    }
                )
                parent_id = None
                continue
            matches = [
                candidate
                for candidate in target_folders
                if (candidate.file_level_path or "") == raw_parent_path
                and normalize_folder_name(candidate.file_name)
                == normalize_folder_name(folder.file_name)
            ]
            if len(matches) > 1:
                return _TargetLocation(
                    display_path="/" + "/".join(display_parts),
                    raw_parent_path=None,
                    folder_id=None,
                    mapping_snapshot=mapping,
                    reason_code="target_folder_ambiguous",
                )
            if matches:
                target = matches[0]
                parent_id = int(target.id)
                raw_parent_path = f"{target.file_level_path or ''}/{target.id}"
                mapping.append(
                    {
                        "source_folder_id": int(folder.id),
                        "source_name": folder.file_name,
                        "target_folder_id": int(target.id),
                        "action": "reused",
                    }
                )
            else:
                mapping.append(
                    {
                        "source_folder_id": int(folder.id),
                        "source_name": folder.file_name,
                        "target_folder_id": None,
                        "action": "planned",
                    }
                )
                parent_id = None
                raw_parent_path = None
        return _TargetLocation(
            display_path="/" + "/".join(part for part in display_parts if part),
            raw_parent_path=raw_parent_path,
            folder_id=parent_id,
            mapping_snapshot=mapping,
        )

    async def _target_conflict_context(
        self,
        target_files: list[KnowledgeFile],
    ) -> tuple[
        dict[int, str],
        dict[int, bool],
        dict[int, bool],
        dict[int, dict[str, Any]],
    ]:
        target_ids = {int(file.id) for file in target_files}
        versions = await self.source_repository.find_versions_by_file_ids(target_ids)
        file_unit_key = {
            int(version.knowledge_file_id): f"document:{version.document_id}"
            for version in versions
        }
        file_version_snapshot = {
            int(version.knowledge_file_id): {
                "document_id": int(version.document_id),
                "version_id": int(version.id),
                "version_no": int(version.version_no),
                "is_primary": bool(version.is_primary),
            }
            for version in versions
        }
        document_ids = {int(version.document_id) for version in versions}
        documents = {
            int(item.id): item
            for item in await self.source_repository.find_documents_by_ids(document_ids)
        }
        all_versions = await self.source_repository.find_versions_by_document_ids(
            document_ids
        )
        entries = await self.source_repository.find_entries_by_document_ids(document_ids)
        protected = {
            document_id: any(
                int(entry.reference_document_id or 0) == document_id
                and entry.entry_type
                in {
                    KnowledgeFileEntryType.PUBLISH.value,
                    KnowledgeFileEntryType.SHARE.value,
                }
                and entry.entry_status == KnowledgeFileEntryStatus.ACTIVE.value
                for entry in entries
            )
            for document_id in document_ids
        }
        graph_valid: dict[int, bool] = {}
        for document_id in document_ids:
            document = documents.get(document_id)
            rows = [
                version
                for version in all_versions
                if int(version.document_id) == document_id
            ]
            primary = [version for version in rows if version.is_primary]
            graph_valid[document_id] = bool(
                document
                and document.lifecycle_status
                == KnowledgeDocumentLifecycleStatus.ACTIVE.value
                and len(primary) == 1
                and int(document.primary_version_id or 0) == int(primary[0].id)
                and len({int(version.version_no) for version in rows}) == len(rows)
            )
        return (
            file_unit_key,
            protected,
            graph_valid,
            file_version_snapshot,
        )

    async def run_preflight(self, batch_id: int) -> None:
        changed = await self.repository.compare_and_set_batch_status(
            batch_id,
            {KnowledgeMigrationBatchStatus.PREFLIGHT_QUEUED.value},
            KnowledgeMigrationBatchStatus.PREFLIGHTING.value,
        )
        if not changed:
            return
        await self.repository.commit()
        batch = await self.repository.find_batch_by_id(batch_id)
        if batch is None:
            return
        try:
            selected_files = await self.source_repository.expand_selection(
                batch.source_selection_snapshot
            )
            units, version_by_file_id, _ = await self._build_source_units(
                batch, selected_files
            )
            storage_errors = await self.preflight_inspector.find_storage_errors(
                selected_files
            )
            folders, selected_folder_ids, selected_file_ids = await self._folder_context(
                batch, selected_files
            )
            target_folders = await self.source_repository.list_target_folders(
                batch.target_space_id
            )
            target_files = await self.source_repository.list_target_files(
                batch.target_space_id
            )
            (
                target_file_unit,
                target_protected,
                target_graph_valid,
                target_file_versions,
            ) = await self._target_conflict_context(target_files)
            target_space_rows = await self.source_repository.find_spaces_by_ids(
                {batch.target_space_id}
            )
            if not target_space_rows:
                raise RuntimeError("target knowledge space is no longer available")
            target_model = str(target_space_rows[0].space.model or "")
            source_models = {
                int(item["id"]): str(item.get("model") or "")
                for item in batch.source_spaces_snapshot
            }
            target_by_md5: dict[str, list[KnowledgeFile]] = defaultdict(list)
            for target in target_files:
                if (target.md5 or "").strip():
                    target_by_md5[target.md5.strip()].append(target)

            reservations: set[str] = set()
            output_name_reservations: set[tuple[str, str]] = set()
            output_md5_reservations: set[str] = set()
            overwrite_count = 0
            rows_to_save = []
            for source_unit in units:
                primary_file = source_unit.files[-1]
                source_chain = self._source_chain(
                    primary_file,
                    preserve_structure=batch.preserve_structure,
                    selected_folder_ids=selected_folder_ids,
                    selected_file_ids=selected_file_ids,
                    folders=folders,
                )
                full_source_chain = self._full_source_chain(
                    primary_file,
                    folders,
                )
                location = self._resolve_target_location(
                    batch,
                    source_chain,
                    target_folders,
                )
                reason_code = source_unit.reason_code or location.reason_code
                summary = source_unit.summary
                unit_storage_errors = {
                    storage_errors[int(source_file.id)]
                    for source_file in source_unit.files
                    if int(source_file.id) in storage_errors
                }
                if reason_code is None and unit_storage_errors:
                    reason_code = "source_storage_unavailable"
                    summary = "; ".join(sorted(unit_storage_errors))
                if (
                    reason_code is None
                    and source_models.get(int(primary_file.knowledge_id), "")
                    != target_model
                ):
                    reason_code = "embedding_model_mismatch"
                    summary = "来源与目标知识库向量模型不一致"

                matched: dict[str, set[str]] = defaultdict(set)
                if reason_code is None:
                    for source_file in source_unit.files:
                        if (source_file.md5 or "").strip():
                            for target in target_by_md5.get(
                                source_file.md5.strip(), []
                            ):
                                key = target_file_unit.get(
                                    int(target.id), f"file:{target.id}"
                                )
                                matched[key].add("md5")
                        if location.raw_parent_path is not None:
                            for target in target_files:
                                if (
                                    (target.file_level_path or "")
                                    == location.raw_parent_path
                                    and normalize_folder_name(target.file_name)
                                    == normalize_folder_name(source_file.file_name)
                                ):
                                    key = target_file_unit.get(
                                        int(target.id), f"file:{target.id}"
                                    )
                                    matched[key].add("name")
                    candidates = []
                    for key, reasons in matched.items():
                        document_id = (
                            int(key.split(":", 1)[1])
                            if key.startswith("document:")
                            else None
                        )
                        candidates.append(
                            ConflictCandidate(
                                unit_key=key,
                                matched_by=tuple(sorted(reasons)),
                                has_active_distribution=bool(
                                    document_id
                                    and target_protected.get(document_id, False)
                                ),
                                graph_valid=bool(
                                    document_id is None
                                    or target_graph_valid.get(document_id, False)
                                ),
                            )
                        )
                    resolution = resolve_conflict(
                        strategy=batch.conflict_strategy,
                        candidates=candidates,
                    )
                    if (
                        resolution.overwrite_unit_key
                        and resolution.overwrite_unit_key
                        == source_unit.unit_key
                    ):
                        reason_code = "target_same_canonical_document"
                        summary = "来源 canonical document 不能覆盖自身"
                    elif (
                        resolution.overwrite_unit_key
                        and resolution.overwrite_unit_key in reservations
                    ):
                        reason_code = "target_overwrite_reserved"
                        summary = "覆盖目标已被本批次其他来源单元占用"
                    elif resolution.reason_code:
                        reason_code = resolution.reason_code
                        summary = "目标冲突不满足安全迁移条件"
                    elif resolution.overwrite_unit_key:
                        reservations.add(resolution.overwrite_unit_key)
                        overwrite_count += 1
                else:
                    resolution = resolve_conflict(
                        strategy=batch.conflict_strategy,
                        candidates=(),
                    )

                unit_status = (
                    KnowledgeMigrationUnitStatus.POLICY_SKIPPED.value
                    if reason_code
                    else KnowledgeMigrationUnitStatus.PLANNED.value
                )
                overwrite_snapshot = None
                overwrite_unit_key = (
                    None
                    if reason_code
                    else getattr(
                        resolution,
                        "overwrite_unit_key",
                        None,
                    )
                )
                output_name_keys = {
                    (
                        normalize_folder_name(location.display_path),
                        normalize_folder_name(source_file.file_name),
                    )
                    for source_file in source_unit.files
                }
                output_md5_keys = {
                    str(source_file.md5).strip()
                    for source_file in source_unit.files
                    if str(source_file.md5 or "").strip()
                }
                if reason_code is None and (
                    output_name_keys.intersection(
                        output_name_reservations
                    )
                    or output_md5_keys.intersection(
                        output_md5_reservations
                    )
                ):
                    reason_code = "target_batch_output_conflict"
                    summary = "本批次前序迁移单元已占用相同目标名称或 MD5"
                    unit_status = (
                        KnowledgeMigrationUnitStatus.POLICY_SKIPPED.value
                    )
                    overwrite_unit_key = None
                    overwrite_snapshot = None
                    if resolution.overwrite_unit_key:
                        reservations.discard(
                            resolution.overwrite_unit_key
                        )
                        overwrite_count -= 1
                elif reason_code is None:
                    output_name_reservations.update(output_name_keys)
                    output_md5_reservations.update(output_md5_keys)
                if overwrite_unit_key:
                    overwrite_targets = [
                        target
                        for target in target_files
                        if target_file_unit.get(
                            int(target.id), f"file:{target.id}"
                        )
                        == overwrite_unit_key
                    ]
                    overwrite_snapshot = {
                        "unit_key": overwrite_unit_key,
                        "matched_by": sorted(matched[overwrite_unit_key]),
                        "target_files": [
                            {
                                "record": target.model_dump(mode="json"),
                                "version": target_file_versions.get(
                                    int(target.id)
                                ),
                                "resource_manifest": {
                                    "object_name": target.object_name,
                                    "preview_file_object_name": target.preview_file_object_name,
                                    "bbox_object_name": target.bbox_object_name,
                                    "thumbnails": target.thumbnails,
                                    "converted_object_name": str(target.id),
                                    "pdf_preview_object_name": (
                                        target.user_metadata or {}
                                    ).get("pdf_preview_object_name"),
                                },
                            }
                            for target in overwrite_targets
                        ],
                    }
                unit_row = KnowledgeMigrationUnit(
                    batch_id=batch_id,
                    unit_key=source_unit.unit_key,
                    unit_type=source_unit.unit_type,
                    source_document_id=source_unit.document_id,
                    source_space_id=int(primary_file.knowledge_id),
                    source_space_name=next(
                        (
                            str(item["name"])
                            for item in batch.source_spaces_snapshot
                            if int(item["id"]) == int(primary_file.knowledge_id)
                        ),
                        str(primary_file.knowledge_id),
                    ),
                    source_parent_folder_id=(
                        int(full_source_chain[-1].id)
                        if full_source_chain
                        else None
                    ),
                    source_path_snapshot="/" + "/".join(
                        [folder.file_name for folder in full_source_chain]
                    ),
                    planned_target_folder_id=location.folder_id,
                    planned_target_path_snapshot=location.display_path or "/",
                    status=unit_status,
                    reason_code=reason_code,
                    summary=summary,
                    target_document_id=source_unit.document_id,
                    overwrite_unit_key=overwrite_unit_key,
                    overwrite_snapshot=overwrite_snapshot,
                    folder_mapping_snapshot=location.mapping_snapshot,
                )
                file_rows = []
                for source_file in source_unit.files:
                    version = version_by_file_id.get(int(source_file.id))
                    physical_source_chain = self._full_source_chain(
                        source_file,
                        folders,
                    )
                    file_rows.append(
                        KnowledgeMigrationFile(
                            batch_id=batch_id,
                            unit_id=0,
                            source_file_id=int(source_file.id),
                            source_document_id=source_unit.document_id,
                            source_version_id=(
                                int(version.id) if version is not None else None
                            ),
                            source_version_no=(
                                int(version.version_no)
                                if version is not None
                                else None
                            ),
                            is_primary=bool(
                                version.is_primary if version is not None else False
                            ),
                            source_space_id=int(source_file.knowledge_id),
                            source_space_name=unit_row.source_space_name,
                            source_folder_id=(
                                int(physical_source_chain[-1].id)
                                if physical_source_chain
                                else None
                            ),
                            source_path_snapshot="/" + "/".join(
                                folder.file_name
                                for folder in physical_source_chain
                            ),
                            source_file_name=source_file.file_name,
                            source_metadata_snapshot={
                                "file_size": source_file.file_size,
                                "md5": source_file.md5,
                                "file_encoding": source_file.file_encoding,
                                "file_subcategory_code": source_file.file_subcategory_code,
                                "user_metadata": source_file.user_metadata,
                            },
                            source_resource_manifest={
                                "object_name": source_file.object_name,
                                "preview_file_object_name": source_file.preview_file_object_name,
                                "bbox_object_name": source_file.bbox_object_name,
                                "source_folder_ids": [
                                    int(folder.id)
                                    for folder in physical_source_chain
                                ],
                            },
                            target_space_id=batch.target_space_id,
                            target_space_name=batch.target_space_name,
                            target_folder_id=location.folder_id,
                            target_path_snapshot=location.display_path or "/",
                            target_file_name=source_file.file_name,
                            status=unit_status,
                            reason_code=reason_code,
                            summary=summary,
                        )
                    )
                rows_to_save.append((unit_row, file_rows))

            await self.repository.replace_plan(batch_id, rows_to_save)
            progress = await self.repository.recompute_progress(batch_id)
            batch.scanned_count = len(selected_files)
            batch.total_count = progress.total_count
            batch.executable_count = progress.executable_count
            batch.completed_count = progress.completed_count
            batch.succeeded_count = progress.succeeded_count
            batch.skipped_count = progress.skipped_count
            batch.failed_count = progress.failed_count
            batch.unprocessed_count = progress.unprocessed_count
            batch.overwrite_target_count = overwrite_count
            target_status = (
                KnowledgeMigrationBatchStatus.AWAITING_CONFIRMATION.value
                if overwrite_count > 0
                else KnowledgeMigrationBatchStatus.QUEUED.value
            )
            batch.status = target_status
            batch.current_stage = target_status
            if target_status == KnowledgeMigrationBatchStatus.QUEUED.value:
                batch.queued_at = datetime.now()
            await self.repository.commit()
            if target_status == KnowledgeMigrationBatchStatus.QUEUED.value:
                try:
                    task_id = self.dispatcher.dispatch_execution(
                        batch_id, batch.round_no
                    )
                    if task_id:
                        batch.execution_task_id = task_id
                        await self.repository.commit()
                except Exception as exc:
                    batch.last_error_code = "execution_dispatch_failed"
                    batch.last_error_summary = sanitize_error_summary(str(exc))
                    await self.repository.commit()
        except Exception as exc:
            await self.repository.rollback()
            changed = await self.repository.compare_and_set_batch_status(
                batch_id,
                {KnowledgeMigrationBatchStatus.PREFLIGHTING.value},
                KnowledgeMigrationBatchStatus.FAILED.value,
                last_error_code="preflight_failed",
                last_error_summary=sanitize_error_summary(
                    f"{type(exc).__name__}: {exc}"
                ),
                finished_at=datetime.now(),
            )
            if changed:
                await self.repository.commit()
