from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import or_
from sqlmodel import col, delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeState, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import (
    KnowledgeDocumentVersion,
)
from bisheng.knowledge.domain.models.knowledge_file import (
    FileType,
    KnowledgeFile,
    KnowledgeFileEntryStatus,
    KnowledgeFileEntryType,
    KnowledgeFileProjectionStatus,
    KnowledgeFileStatus,
)
from bisheng.knowledge.domain.models.knowledge_file_pdf_artifact import (
    KnowledgeFilePdfArtifact,
)
from bisheng.knowledge.domain.models.knowledge_file_similarity_candidate import (
    KnowledgeFileSimilarityCandidate,
)
from bisheng.knowledge.domain.models.knowledge_migration import (
    KnowledgeMigrationAttempt,
    KnowledgeMigrationAttemptResult,
    KnowledgeMigrationBatch,
    KnowledgeMigrationBatchStatus,
    KnowledgeMigrationCheckpoint,
    KnowledgeMigrationFile,
    KnowledgeMigrationUnit,
    KnowledgeMigrationUnitStatus,
)
from bisheng.knowledge.domain.models.portal_recommendation_file_projection import (
    PortalRecommendationFileProjection,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_migration_runtime_repository import (
    KnowledgeMigrationRuntimeRepository,
    MigrationRuntimeContext,
    MigrationRuntimeFile,
)
from bisheng.knowledge.domain.services.file_migration.planner import (
    normalize_folder_name,
)
from bisheng.knowledge.domain.services.knowledge_fulltext_lifecycle_hook import (
    commit_tracked_fulltext_changes,
    track_fulltext_file_changes,
)
from bisheng.share_link.domain.models.share_link import (
    ResourceTypeEnum as ShareResourceTypeEnum,
)
from bisheng.share_link.domain.models.share_link import ShareLink
from bisheng.user.domain.models.user import User


class KnowledgeMigrationRuntimeRepositoryImpl(KnowledgeMigrationRuntimeRepository):
    def __init__(self, session: AsyncSession):
        self.session = session
        track_fulltext_file_changes(session)

    async def _commit(self) -> None:
        await commit_tracked_fulltext_changes(
            self.session,
            trigger_type="knowledge_migration_updated",
        )

    async def find_batch_modes(self, unit_ids: list[int]) -> dict[int, bool]:
        rows = (
            await self.session.exec(
                select(KnowledgeMigrationUnit.id, KnowledgeMigrationBatch.preserve_link)
                .join(KnowledgeMigrationBatch, KnowledgeMigrationBatch.id == KnowledgeMigrationUnit.batch_id)
                .where(col(KnowledgeMigrationUnit.id).in_(unit_ids))
            )
        ).all()
        return {int(unit_id): bool(mode) for unit_id, mode in rows}

    async def _control_rows(
        self,
        unit_id: int,
        *,
        for_update: bool = False,
    ) -> tuple[
        KnowledgeMigrationBatch,
        KnowledgeMigrationUnit,
        list[KnowledgeMigrationFile],
    ]:
        unit = (
            await self.session.exec(
                select(KnowledgeMigrationUnit).where(
                    KnowledgeMigrationUnit.id == unit_id
                )
            )
        ).first()
        if unit is None:
            raise LookupError(f"migration unit not found: {unit_id}")
        batch_statement = select(KnowledgeMigrationBatch).where(
            KnowledgeMigrationBatch.id == unit.batch_id
        )
        if for_update:
            batch_statement = batch_statement.with_for_update()
        batch = (await self.session.exec(batch_statement)).one()
        if for_update:
            unit = (
                await self.session.exec(
                    select(KnowledgeMigrationUnit)
                    .where(KnowledgeMigrationUnit.id == unit_id)
                    .with_for_update()
                )
            ).one()
        file_statement = (
            select(KnowledgeMigrationFile)
            .where(KnowledgeMigrationFile.unit_id == unit_id)
            .order_by(
                KnowledgeMigrationFile.source_version_no,
                KnowledgeMigrationFile.id,
            )
        )
        if for_update:
            file_statement = file_statement.with_for_update()
        files = list((await self.session.exec(file_statement)).all())
        return batch, unit, files

    async def _active_control_rows(
        self,
        *,
        unit_id: int,
        attempt_id: int,
        execution_token: str,
    ) -> tuple[
        KnowledgeMigrationBatch,
        KnowledgeMigrationUnit,
        list[KnowledgeMigrationFile],
    ]:
        identity = (
            await self.session.exec(
                select(KnowledgeMigrationAttempt).where(
                    KnowledgeMigrationAttempt.id == attempt_id
                )
            )
        ).first()
        if identity is None or int(identity.unit_id) != unit_id:
            raise RuntimeError("migration attempt is no longer active")
        batch, unit, control_files = await self._control_rows(
            unit_id,
            for_update=True,
        )
        attempt = (
            await self.session.exec(
                select(KnowledgeMigrationAttempt)
                .where(KnowledgeMigrationAttempt.id == attempt_id)
                .with_for_update()
            )
        ).first()
        if (
            attempt is None
            or int(attempt.unit_id) != unit_id
            or attempt.execution_token != execution_token
            or attempt.result
            != KnowledgeMigrationAttemptResult.RUNNING.value
            or batch.status != KnowledgeMigrationBatchStatus.RUNNING.value
            or unit.status != KnowledgeMigrationUnitStatus.RUNNING.value
            or int(unit.attempt_count) != int(attempt.attempt_no)
        ):
            raise RuntimeError("migration attempt is no longer active")
        return batch, unit, control_files

    async def _runtime_context(
        self,
        batch: KnowledgeMigrationBatch,
        unit: KnowledgeMigrationUnit,
        control_files: list[KnowledgeMigrationFile],
    ) -> MigrationRuntimeContext:
        source_ids = {row.source_file_id for row in control_files}
        target_ids = {
            int(row.target_file_id)
            for row in control_files
            if row.target_file_id is not None
        }
        source_files = {
            int(row.id): row
            for row in (
                await self.session.exec(select(KnowledgeFile).where(col(KnowledgeFile.id).in_(source_ids | target_ids)))
            ).all()
        }
        target_files = {file_id: source_files[file_id] for file_id in target_ids if file_id in source_files}
        source_files = {file_id: source_files[file_id] for file_id in source_ids if file_id in source_files}
        if set(source_files) != source_ids:
            raise RuntimeError("one or more source files are missing")
        if target_ids != set(target_files):
            raise RuntimeError("one or more prepared target files are missing")
        space_ids = {file.knowledge_id for file in source_files.values()} | {
            batch.target_space_id
        }
        spaces = {
            int(row.id): row
            for row in (
                await self.session.exec(
                    select(Knowledge).where(col(Knowledge.id).in_(space_ids))
                )
            ).all()
        }
        target_space = spaces.get(batch.target_space_id)
        if target_space is None or target_space.user_id is None:
            raise RuntimeError("target knowledge space or owner is missing")
        owner = (
            await self.session.exec(
                select(User).where(
                    User.user_id == int(target_space.user_id),
                    User.delete == 0,
                )
            )
        ).first()
        if owner is None:
            raise RuntimeError("target knowledge-space owner is disabled or missing")
        created_folder_ids = [
            int(item["target_folder_id"])
            for item in unit.folder_mapping_snapshot or []
            if item.get("action") == "created"
            and item.get("target_folder_id") is not None
        ]
        created_folders = []
        if created_folder_ids:
            created_folders = list(
                (
                    await self.session.exec(
                        select(KnowledgeFile).where(
                            col(KnowledgeFile.id).in_(created_folder_ids)
                        )
                    )
                ).all()
            )
        return MigrationRuntimeContext(
            batch=batch,
            unit=unit,
            files=tuple(
                MigrationRuntimeFile(
                    control=control,
                    source=source_files[control.source_file_id],
                    target=target_files[int(control.target_file_id)],
                )
                for control in control_files
            ),
            source_spaces={
                space_id: spaces[space_id]
                for space_id in spaces
                if space_id != batch.target_space_id
            },
            target_space=target_space,
            target_owner=owner,
            created_folders=tuple(created_folders),
        )

    async def load_contexts(self, unit_ids: list[int]) -> dict[int, MigrationRuntimeContext]:
        """一页单元共用控制行、文件、空间和所有者查询。"""
        if not unit_ids:
            return {}
        units = list(
            (
                await self.session.exec(
                    select(KnowledgeMigrationUnit).where(col(KnowledgeMigrationUnit.id).in_(unit_ids))
                )
            ).all()
        )
        batches = {
            row.id: row
            for row in (
                await self.session.exec(
                    select(KnowledgeMigrationBatch).where(
                        col(KnowledgeMigrationBatch.id).in_({unit.batch_id for unit in units})
                    )
                )
            ).all()
        }
        controls = list(
            (
                await self.session.exec(
                    select(KnowledgeMigrationFile)
                    .where(col(KnowledgeMigrationFile.unit_id).in_(unit_ids))
                    .order_by(KnowledgeMigrationFile.id)
                )
            ).all()
        )
        ids = {row.source_file_id for row in controls} | {row.target_file_id for row in controls if row.target_file_id}
        folder_ids = {
            int(value["target_folder_id"])
            for unit in units
            for value in unit.folder_mapping_snapshot or []
            if value.get("action") == "created" and value.get("target_folder_id")
        }
        files = {
            row.id: row
            for row in (
                await self.session.exec(select(KnowledgeFile).where(col(KnowledgeFile.id).in_(ids | folder_ids)))
            ).all()
        }
        space_ids = {file.knowledge_id for file in files.values()} | {
            batch.target_space_id for batch in batches.values()
        }
        spaces = {
            row.id: row
            for row in (await self.session.exec(select(Knowledge).where(col(Knowledge.id).in_(space_ids)))).all()
        }
        owners = {
            row.user_id: row
            for row in (
                await self.session.exec(
                    select(User).where(
                        col(User.user_id).in_({space.user_id for space in spaces.values()}), User.delete == 0
                    )
                )
            ).all()
        }
        result = {}
        for unit in units:
            batch = batches[unit.batch_id]
            control_files = [row for row in controls if row.unit_id == unit.id]
            target_space = spaces.get(batch.target_space_id)
            if (
                not control_files
                or target_space is None
                or target_space.user_id not in owners
                or any(row.source_file_id not in files or row.target_file_id not in files for row in control_files)
            ):
                # 缺失状态交给该单元自己的校验，不能使其他单元失败。
                continue
            result[int(unit.id)] = MigrationRuntimeContext(
                batch=batch,
                unit=unit,
                files=tuple(
                    MigrationRuntimeFile(row, files[row.source_file_id], files[row.target_file_id])
                    for row in control_files
                ),
                source_spaces={
                    key: value
                    for key, value in spaces.items()
                    if key != batch.target_space_id
                    and key in {files[row.source_file_id].knowledge_id for row in control_files}
                },
                target_space=target_space,
                target_owner=owners[target_space.user_id],
                created_folders=tuple(
                    files[int(value["target_folder_id"])]
                    for value in unit.folder_mapping_snapshot or []
                    if value.get("action") == "created" and value.get("target_folder_id") in files
                ),
            )
        return result

    async def load_context(self, unit_id: int) -> MigrationRuntimeContext:
        batch, unit, control_files = await self._control_rows(unit_id)
        if any(row.target_file_id is None for row in control_files):
            raise RuntimeError("target rows have not been prepared")
        return await self._runtime_context(batch, unit, control_files)

    async def _prepare_target_folder(
        self,
        batch: KnowledgeMigrationBatch,
        unit: KnowledgeMigrationUnit,
        owner: User,
    ) -> tuple[int | None, str, int, list[dict[str, Any]]]:
        parent_folder = None
        parent_path = ""
        level = 0
        if batch.target_folder_id is not None:
            parent_folder = (
                await self.session.exec(
                    select(KnowledgeFile)
                    .where(
                        KnowledgeFile.id == batch.target_folder_id,
                        KnowledgeFile.knowledge_id == batch.target_space_id,
                        KnowledgeFile.file_type == FileType.DIR.value,
                        KnowledgeFile.deleted_at.is_(None),
                    )
                    .with_for_update()
                )
            ).first()
            if parent_folder is None:
                raise RuntimeError("target folder no longer exists")
            parent_path = f"{parent_folder.file_level_path or ''}/{parent_folder.id}"
            level = int(parent_folder.level or 0) + 1
        else:
            await self.session.exec(
                select(Knowledge.id)
                .where(Knowledge.id == batch.target_space_id)
                .with_for_update()
            )

        mapping = []
        for planned in unit.folder_mapping_snapshot or []:
            matches = list(
                (
                    await self.session.exec(
                        select(KnowledgeFile).where(
                            KnowledgeFile.knowledge_id == batch.target_space_id,
                            KnowledgeFile.file_type == FileType.DIR.value,
                            KnowledgeFile.file_level_path == parent_path,
                            KnowledgeFile.deleted_at.is_(None),
                        )
                    )
                ).all()
            )
            matches = [
                folder
                for folder in matches
                if normalize_folder_name(folder.file_name)
                == normalize_folder_name(str(planned["source_name"]))
            ]
            if len(matches) > 1:
                raise RuntimeError("target folder became ambiguous after preflight")
            if matches:
                folder = matches[0]
                action = "created" if planned.get("action") == "created" and planned.get("target_folder_id") == folder.id else "reused"
            else:
                folder = KnowledgeFile(
                    tenant_id=batch.tenant_id,
                    knowledge_id=batch.target_space_id,
                    user_id=int(owner.user_id),
                    user_name=owner.user_name,
                    updater_id=int(owner.user_id),
                    updater_name=owner.user_name,
                    file_name=str(planned["source_name"]),
                    file_type=FileType.DIR.value,
                    file_level_path=parent_path,
                    level=level,
                    status=KnowledgeFileStatus.SUCCESS.value,
                )
                self.session.add(folder)
                await self.session.flush()
                action = "created"
            mapping.append(
                {
                    "source_folder_id": int(planned["source_folder_id"]),
                    "source_name": str(planned["source_name"]),
                    "target_folder_id": int(folder.id),
                    "action": action,
                }
            )
            parent_folder = folder
            parent_path = f"{folder.file_level_path or ''}/{folder.id}"
            level = int(folder.level or 0) + 1
        return (
            int(parent_folder.id) if parent_folder is not None else None,
            parent_path,
            level,
            mapping,
        )

    @staticmethod
    def _target_file_clone(
        source: KnowledgeFile,
        *,
        batch: KnowledgeMigrationBatch,
        owner: User,
        parent_path: str,
        level: int,
    ) -> KnowledgeFile:
        payload = source.model_dump()
        for field in ("id", "create_time", "update_time", "deleted_at"):
            payload.pop(field, None)
        payload.update(
            {
                "tenant_id": batch.tenant_id,
                "knowledge_id": batch.target_space_id,
                "user_id": int(owner.user_id),
                "user_name": owner.user_name,
                "updater_id": int(owner.user_id),
                "updater_name": owner.user_name,
                "file_level_path": parent_path,
                "level": level,
                "status": KnowledgeFileStatus.PROCESSING.value,
                "object_name": None,
                "preview_file_object_name": None,
                "bbox_object_name": "",
                "thumbnails": None,
                "projection_status": KnowledgeFileProjectionStatus.PENDING.value,
                "projection_retry_count": 0,
                "projection_next_retry_at": None,
                "projection_lease_owner": None,
                "projection_lease_until": None,
                "projection_last_error": None,
            }
        )
        metadata = dict(payload.get("user_metadata") or {})
        metadata.pop("pdf_preview_object_name", None)
        metadata.pop("pdf_preview_source_md5", None)
        payload["user_metadata"] = metadata
        if source.entry_type == KnowledgeFileEntryType.MANAGER.value:
            payload["entry_status"] = KnowledgeFileEntryStatus.PREPARING.value
        # Prepared rows must not participate in canonical projection before switch.
        payload["reference_document_id"] = None
        return KnowledgeFile(**payload)

    async def prepare_target_rows(
        self,
        unit_id: int,
        *,
        attempt_id: int,
        execution_token: str,
    ) -> MigrationRuntimeContext:
        batch, unit, control_files = await self._active_control_rows(
            unit_id=unit_id,
            attempt_id=attempt_id,
            execution_token=execution_token,
        )
        if control_files and all(row.target_file_id is not None for row in control_files):
            await self._snapshot_source_content(unit, control_files)
            await self._commit()
            return await self._runtime_context(batch, unit, control_files)
        if any(row.target_file_id is not None for row in control_files):
            raise RuntimeError("partial target-row manifest is not recoverable")
        target_space = (
            await self.session.exec(
                select(Knowledge)
                .where(Knowledge.id == batch.target_space_id)
                .with_for_update()
            )
        ).first()
        if target_space is None or target_space.user_id is None:
            raise RuntimeError("target knowledge space or owner is missing")
        owner = (
            await self.session.exec(
                select(User).where(
                    User.user_id == int(target_space.user_id),
                    User.delete == 0,
                )
            )
        ).first()
        if owner is None:
            raise RuntimeError("target knowledge-space owner is disabled or missing")
        target_folder_id, parent_path, level, mapping = (
            await self._prepare_target_folder(batch, unit, owner)
        )
        source_ids = {row.source_file_id for row in control_files}
        sources = {
            int(row.id): row
            for row in (
                await self.session.exec(
                    select(KnowledgeFile)
                    .where(col(KnowledgeFile.id).in_(source_ids))
                    .with_for_update()
                )
            ).all()
        }
        if set(sources) != source_ids:
            raise RuntimeError("source file disappeared before target preparation")
        unsupported_entry_types = {
            KnowledgeFileEntryType.PUBLISH.value,
            KnowledgeFileEntryType.SHARE.value,
            KnowledgeFileEntryType.PROJECTION_TOMBSTONE.value,
        }
        for source in sources.values():
            if source.status != KnowledgeFileStatus.SUCCESS.value:
                raise RuntimeError("source file is no longer in SUCCESS state")
            if source.entry_type in unsupported_entry_types:
                raise RuntimeError("source file became an unsupported logic entry")
            if (
                source.entry_type == KnowledgeFileEntryType.MANAGER.value
                and source.entry_status
                != KnowledgeFileEntryStatus.ACTIVE.value
            ):
                raise RuntimeError("source manager is no longer active")
        source_space_ids = {
            int(source.knowledge_id) for source in sources.values()
        }
        source_spaces = list(
            (
                await self.session.exec(
                    select(Knowledge).where(
                        col(Knowledge.id).in_(source_space_ids)
                    )
                )
            ).all()
        )
        if len(source_spaces) != len(source_space_ids) or any(
            space.type != KnowledgeTypeEnum.SPACE.value
            or space.state != KnowledgeState.PUBLISHED.value
            or int(space.tenant_id or 1) != int(batch.tenant_id)
            for space in [*source_spaces, target_space]
        ):
            raise RuntimeError("source and target must be active spaces in the same tenant")
        if unit.source_document_id is None:
            raise RuntimeError("shared migration requires a canonical document")
        await self._snapshot_source_content(unit, control_files)
        for control in control_files:
            source = sources[control.source_file_id]
            # 原位迁移保留所有物理标识与对象；目标目录仅在切换时生效。
            control.target_file_id = int(source.id)
            control.target_folder_id = target_folder_id
            control.target_resource_manifest = {
                **(control.target_resource_manifest or {}),
                "metadata_only": True,
                "target_file_level_path": parent_path,
                "target_level": level,
                "created_folder_ids": [
                    int(item["target_folder_id"]) for item in mapping if item["action"] == "created"
                ],
            }
            self.session.add(control)
        unit.planned_target_folder_id = target_folder_id
        unit.folder_mapping_snapshot = mapping
        self.session.add(unit)
        await self._commit()
        return await self.load_context(unit_id)

    async def _snapshot_source_content(self, unit, files) -> None:
        if files and all((row.source_resource_manifest or {}).get("shared_content") for row in files):
            for row in files:
                row.target_resource_manifest = {
                    **(row.target_resource_manifest or {}),
                    "source_content": row.source_resource_manifest["shared_content"],
                }
                self.session.add(row)
            return
        document = await self.session.get(KnowledgeDocument, unit.source_document_id)
        version = await self.session.get(KnowledgeDocumentVersion, document.primary_version_id) if document else None
        if version is None:
            raise RuntimeError("migration source content identity is unavailable")
        identity = {
            "document_id": int(document.id),
            "version_id": int(version.id),
            "file_id": int(version.knowledge_file_id),
            "generation": int(document.content_generation),
        }
        for row in files:
            # 来源身份独立于可被补偿清空的目标清单，合并提交后的重试仍可恢复。
            row.source_resource_manifest = {**(row.source_resource_manifest or {}), "shared_content": identity}
            row.target_resource_manifest = {**(row.target_resource_manifest or {}), "source_content": identity}
            self.session.add(row)

    @staticmethod
    def _fingerprint(file: KnowledgeFile | dict[str, Any]) -> dict[str, Any]:
        value = file if isinstance(file, dict) else file.model_dump(mode="json")
        return {
            key: value.get(key)
            for key in (
                "id",
                "knowledge_id",
                "file_name",
                "file_level_path",
                "md5",
                "reference_document_id",
                "entry_type",
                "entry_status",
                "status",
                "deleted_at",
                "update_time",
            )
        }

    @staticmethod
    def _document_fingerprint(
        document: KnowledgeDocument | dict[str, Any],
    ) -> dict[str, Any]:
        value = document if isinstance(document, dict) else document.model_dump(mode="json")
        return {
            key: value.get(key)
            for key in (
                "id",
                "tenant_id",
                "knowledge_id",
                "file_level_path",
                "level",
                "primary_version_id",
                "lifecycle_status",
                "deleted_at",
                "update_time",
            )
        }

    @staticmethod
    def _version_fingerprint(
        version: KnowledgeDocumentVersion | dict[str, Any],
    ) -> dict[str, Any]:
        value = version if isinstance(version, dict) else version.model_dump(mode="json")
        return {
            key: value.get(key)
            for key in (
                "id",
                "document_id",
                "knowledge_file_id",
                "version_no",
                "is_primary",
                "create_time",
                "update_time",
            )
        }

    async def _apply_overwrite_switch(
        self,
        unit: KnowledgeMigrationUnit,
    ) -> None:
        snapshot = unit.overwrite_snapshot or {}
        items = snapshot.get("target_files") or []
        if not items:
            return
        expected = {
            int(item["record"]["id"]): self._fingerprint(item["record"])
            for item in items
        }
        current_rows = list(
            (
                await self.session.exec(
                    select(KnowledgeFile)
                    .where(col(KnowledgeFile.id).in_(set(expected)))
                    .with_for_update()
                )
            ).all()
        )
        actual = {int(row.id): self._fingerprint(row) for row in current_rows}
        if actual != expected:
            raise RuntimeError("overwrite target changed after confirmation")
        if any(row.projection_lease_owner or row.projection_status == "processing" for row in current_rows):
            raise RuntimeError("overwrite target has an in-flight shared projection")
        expected_document = snapshot.get("document")
        expected_versions = snapshot.get("versions") or []
        if expected_document is not None:
            document_id = int(expected_document["id"])
            current_document = (
                await self.session.exec(
                    select(KnowledgeDocument).where(KnowledgeDocument.id == document_id).with_for_update()
                )
            ).first()
            current_versions = list(
                (
                    await self.session.exec(
                        select(KnowledgeDocumentVersion)
                        .where(KnowledgeDocumentVersion.document_id == document_id)
                        .order_by(
                            KnowledgeDocumentVersion.version_no,
                            KnowledgeDocumentVersion.id,
                        )
                        .with_for_update()
                    )
                ).all()
            )
            expected_version_fingerprints = sorted(
                (self._version_fingerprint(version) for version in expected_versions),
                key=lambda value: int(value["id"]),
            )
            actual_version_fingerprints = sorted(
                (self._version_fingerprint(version) for version in current_versions),
                key=lambda value: int(value["id"]),
            )
            expected_version_file_ids = {int(version["knowledge_file_id"]) for version in expected_versions}
            if (
                current_document is None
                or self._document_fingerprint(current_document) != self._document_fingerprint(expected_document)
                or actual_version_fingerprints != expected_version_fingerprints
                or expected_version_file_ids != set(expected)
            ):
                raise RuntimeError("overwrite target document graph changed after confirmation")
        elif expected_versions:
            raise RuntimeError("overwrite target document graph changed after confirmation")
        overwrite_document_ids = (
            {int(expected_document["id"])}
            if expected_document is not None
            else {
                int(row.reference_document_id)
                for row in current_rows
                if row.reference_document_id is not None
            }
        )
        if (
            unit.source_document_id is not None
            and int(unit.source_document_id) in overwrite_document_ids
        ):
            raise RuntimeError("source canonical document cannot overwrite itself")
        if overwrite_document_ids:
            protected = (
                await self.session.exec(
                    select(KnowledgeFile.id).where(
                        col(KnowledgeFile.reference_document_id).in_(
                            overwrite_document_ids
                        ),
                        col(KnowledgeFile.entry_type).in_(
                            {
                                KnowledgeFileEntryType.PUBLISH.value,
                                KnowledgeFileEntryType.SHARE.value,
                            }
                        ),
                        KnowledgeFile.entry_status
                        == KnowledgeFileEntryStatus.ACTIVE.value,
                    )
                )
            ).first()
            if protected is not None:
                raise RuntimeError(
                    "overwrite target gained an active distribution entry"
                )
        target_ids = set(expected)
        conditions = [
            col(KnowledgeFileSimilarityCandidate.source_file_id).in_(target_ids),
            col(KnowledgeFileSimilarityCandidate.candidate_file_id).in_(target_ids),
        ]
        if overwrite_document_ids:
            conditions.append(
                col(KnowledgeFileSimilarityCandidate.candidate_document_id).in_(
                    overwrite_document_ids
                )
            )
        await self.session.exec(
            delete(KnowledgeFileSimilarityCandidate).where(or_(*conditions))
        )
        await self.session.exec(
            delete(PortalRecommendationFileProjection).where(
                col(PortalRecommendationFileProjection.file_id).in_(target_ids)
            )
        )
        await self.session.exec(
            delete(ShareLink).where(
                ShareLink.resource_type
                == ShareResourceTypeEnum.KNOWLEDGE_SPACE_FILE,
                col(ShareLink.resource_id).in_({str(value) for value in target_ids}),
            )
        )
        overwrite_artifacts = list(
            (
                await self.session.exec(
                    select(KnowledgeFilePdfArtifact).where(
                        col(
                            KnowledgeFilePdfArtifact.knowledge_file_id
                        ).in_(target_ids)
                    )
                )
            ).all()
        )
        snapshot["pdf_artifacts"] = [
            artifact.model_dump(mode="json")
            for artifact in overwrite_artifacts
        ]
        unit.overwrite_snapshot = snapshot
        self.session.add(unit)
        await self.session.exec(
            delete(KnowledgeFilePdfArtifact).where(
                col(KnowledgeFilePdfArtifact.knowledge_file_id).in_(target_ids)
            )
        )
        if overwrite_document_ids:
            await self.session.exec(
                delete(KnowledgeDocumentVersion).where(
                    col(KnowledgeDocumentVersion.document_id).in_(
                        overwrite_document_ids
                    )
                )
            )
            await self.session.exec(
                delete(KnowledgeDocument).where(
                    col(KnowledgeDocument.id).in_(overwrite_document_ids)
                )
            )
        await self.session.exec(
            delete(KnowledgeFile).where(col(KnowledgeFile.id).in_(target_ids))
        )

    async def _validate_current_conflicts(
        self,
        *,
        batch: KnowledgeMigrationBatch,
        unit: KnowledgeMigrationUnit,
        sources: list[KnowledgeFile],
        targets: list[KnowledgeFile],
    ) -> None:
        new_target_ids = {int(row.id) for row in targets}
        confirmed_target_ids = {
            int(item["record"]["id"])
            for item in (unit.overwrite_snapshot or {}).get(
                "target_files", []
            )
        }
        source_md5_values = {
            str(row.md5).strip()
            for row in sources
            if str(row.md5 or "").strip()
        }
        target_parent_paths = {
            str(row.file_level_path or "") for row in targets
        }
        statement = select(KnowledgeFile).where(
            KnowledgeFile.knowledge_id == batch.target_space_id,
            KnowledgeFile.file_type == FileType.FILE.value,
            KnowledgeFile.deleted_at.is_(None),
        )
        candidates = list((await self.session.exec(statement)).all())
        unexpected = []
        target_names_by_path = {
            (
                str(row.file_level_path or ""),
                normalize_folder_name(row.file_name),
            )
            for row in targets
        }
        for candidate in candidates:
            candidate_id = int(candidate.id)
            if candidate_id in new_target_ids:
                continue
            name_conflict = (
                str(candidate.file_level_path or "") in target_parent_paths
                and (
                    str(candidate.file_level_path or ""),
                    normalize_folder_name(candidate.file_name),
                )
                in target_names_by_path
            )
            md5_conflict = (
                bool(str(candidate.md5 or "").strip())
                and str(candidate.md5).strip() in source_md5_values
            )
            if (
                name_conflict or md5_conflict
            ) and candidate_id not in confirmed_target_ids:
                unexpected.append(candidate_id)
        if unexpected:
            raise RuntimeError(
                "target conflict set changed after preflight: "
                f"{sorted(unexpected)}"
            )

    async def activate_switch(
        self,
        unit_id: int,
        *,
        attempt_id: int,
        execution_token: str,
    ) -> None:
        batch, unit, control_files = await self._active_control_rows(
            unit_id=unit_id,
            attempt_id=attempt_id,
            execution_token=execution_token,
        )
        target_ids = {int(row.target_file_id) for row in control_files if row.target_file_id is not None}
        if len(target_ids) != len(control_files):
            raise RuntimeError("target rows are incomplete")
        source_ids = {row.source_file_id for row in control_files}
        sources = list(
            (
                await self.session.exec(
                    select(KnowledgeFile)
                    .where(col(KnowledgeFile.id).in_(source_ids))
                    .with_for_update()
                )
            ).all()
        )
        targets = list(
            (
                await self.session.exec(
                    select(KnowledgeFile)
                    .where(col(KnowledgeFile.id).in_(target_ids))
                    .with_for_update()
                )
            ).all()
        )
        if len(sources) != len(source_ids) or len(targets) != len(target_ids):
            raise RuntimeError("source or target rows changed before switch")
        metadata_only = all(row.target_file_id == row.source_file_id for row in control_files)
        manifests = {row.source_file_id: row.target_resource_manifest or {} for row in control_files}
        planned_targets = (
            [
                row.model_copy(update={"file_level_path": manifests[int(row.id)].get("target_file_level_path", "")})
                for row in targets
            ]
            if metadata_only
            else targets
        )
        await self._validate_current_conflicts(
            batch=batch,
            unit=unit,
            sources=sources,
            targets=planned_targets,
        )
        await self._apply_overwrite_switch(unit)
        target_by_id = {int(row.id): row for row in targets}
        source_by_id = {int(row.id): row for row in sources}
        if unit.unit_type == "version_chain":
            if unit.source_document_id is None:
                raise RuntimeError("version-chain unit has no canonical document")
            document = (
                await self.session.exec(
                    select(KnowledgeDocument)
                    .where(KnowledgeDocument.id == unit.source_document_id)
                    .with_for_update()
                )
            ).first()
            if document is None:
                raise RuntimeError("canonical document disappeared before switch")
            active_entries = list((await self.session.exec(select(KnowledgeFile).where(
                KnowledgeFile.reference_document_id == unit.source_document_id,
                KnowledgeFile.entry_status == KnowledgeFileEntryStatus.ACTIVE.value,
            ).with_for_update())).all())
            if any(entry.projection_lease_owner or entry.projection_status == "processing" for entry in active_entries):
                raise RuntimeError("source canonical document has an in-flight shared projection")
            managers = [entry for entry in active_entries if entry.entry_type == "manager"]
            if len(managers) != 1 or int(managers[0].id) not in source_ids:
                raise RuntimeError("source canonical manager changed before switch")
            versions = list(
                (
                    await self.session.exec(
                        select(KnowledgeDocumentVersion)
                        .where(
                            KnowledgeDocumentVersion.document_id
                            == unit.source_document_id
                        )
                        .with_for_update()
                    )
                ).all()
            )
            target_id_by_source = {
                row.source_file_id: int(row.target_file_id)
                for row in control_files
            }
            if {
                int(version.knowledge_file_id) for version in versions
            } != set(target_id_by_source):
                raise RuntimeError("canonical version graph changed before switch")
            primary_versions = [version for version in versions if version.is_primary]
            if (len(primary_versions) != 1 or primary_versions[0].id != document.primary_version_id
                    or primary_versions[0].knowledge_file_id != managers[0].id):
                raise RuntimeError("canonical primary version changed before switch")
            for version in versions:
                version.knowledge_file_id = target_id_by_source[
                    int(version.knowledge_file_id)
                ]
                self.session.add(version)
            document.knowledge_id = batch.target_space_id
            # 内容未改变，迁移只推进入口代次。
            document.file_level_path = planned_targets[0].file_level_path or ""
            document.level = manifests[int(sources[0].id)].get("target_level", planned_targets[0].level)
            self.session.add(document)
        target_space = await self.session.get(Knowledge, batch.target_space_id)
        target_owner = await self.session.get(User, target_space.user_id)
        for control in control_files:
            source = source_by_id[control.source_file_id]
            target = target_by_id[int(control.target_file_id)]
            target.status = KnowledgeFileStatus.SUCCESS.value
            if metadata_only:
                target.knowledge_id = batch.target_space_id
                target.file_level_path = manifests[int(source.id)].get("target_file_level_path", "")
                target.level = manifests[int(source.id)].get("target_level", 0)
                target.user_id, target.user_name = int(target_owner.user_id), target_owner.user_name
                target.updater_id, target.updater_name = int(target_owner.user_id), target_owner.user_name
            if source.entry_type == KnowledgeFileEntryType.MANAGER.value:
                target.reference_document_id = source.reference_document_id
                target.entry_type = KnowledgeFileEntryType.MANAGER.value
                target.entry_status = KnowledgeFileEntryStatus.ACTIVE.value
                if not metadata_only:
                    source.entry_status = KnowledgeFileEntryStatus.DELETING.value
                    source.reference_document_id = None
                    source.entry_type = None
                target.desired_entry_generation += 1
            if not metadata_only:
                source.status = KnowledgeFileStatus.PROCESSING.value
            self.session.add(source)
            self.session.add(target)
        if unit.source_document_id is not None:
            from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
                KnowledgeFileRepositoryImpl,
            )

            await self.session.flush()
            await KnowledgeFileRepositoryImpl(self.session).mark_document_entries_content_generation(
                int(unit.source_document_id), int(document.content_generation),
            )
            # 元数据迁移由迁移检查点恢复，禁止普通投影任务抢先解析。
            for entry in [*active_entries, *targets]:
                if entry.reference_document_id == document.id and entry.entry_status == "active":
                    entry.projection_status = KnowledgeFileProjectionStatus.PENDING.value
                    entry.projection_next_retry_at = datetime(9999, 1, 1)
                    self.session.add(entry)
        unit.checkpoint = KnowledgeMigrationCheckpoint.DB_SWITCHED.value
        self.session.add(unit)
        for control in control_files:
            control.checkpoint = KnowledgeMigrationCheckpoint.DB_SWITCHED.value
            self.session.add(control)
        await self._commit()

    async def shared_projection_plan(self, unit_id: int, *, attempt_id: int, execution_token: str) -> dict:
        batch, unit, _files = await self._active_control_rows(
            unit_id=unit_id, attempt_id=attempt_id, execution_token=execution_token,
        )
        if unit.checkpoint not in {"db_switched", "source_external_cleaned", "source_rows_cleaned", "completed"}:
            raise RuntimeError("shared projection cannot run before the migration switch")
        document_id = unit.target_document_id or unit.source_document_id
        document = (
            (
                await self.session.exec(
                    select(KnowledgeDocument).where(KnowledgeDocument.id == document_id).with_for_update()
                )
            ).first()
            if document_id
            else None
        )
        if (document is None or int(document.tenant_id or 1) != int(batch.tenant_id)
                or document.knowledge_id != batch.target_space_id or document.lifecycle_status != "active"):
            raise RuntimeError("migration canonical destination changed")
        deleted_document_ids = []
        candidates = []
        if batch.preserve_link and unit.source_document_id != document_id:
            # Publish merge rebinds every source entry to the retained target
            # document. Its old canonical content must also be tombstoned.
            candidates.append(int(unit.source_document_id))
        elif not batch.preserve_link:
            snapshot = unit.overwrite_snapshot or {}
            old = snapshot.get("document")
            if old:
                candidates.append(int(old["id"]))
        for old_id in candidates:
            if old_id == int(document_id) or await self.session.get(KnowledgeDocument, old_id) is not None:
                raise RuntimeError("overwrite canonical document is still in use")
            remaining = (await self.session.exec(select(KnowledgeFile.id).where(
                KnowledgeFile.reference_document_id == old_id,
                KnowledgeFile.entry_status == "active",
            ))).first()
            if remaining is not None:
                raise RuntimeError("overwrite canonical document still has active entries")
            deleted_document_ids.append(old_id)
        source_content = next(
            (
                (row.source_resource_manifest or {}).get("shared_content")
                or (row.target_resource_manifest or {}).get("source_content")
                for row in _files
                if (row.source_resource_manifest or {}).get("shared_content")
                or (row.target_resource_manifest or {}).get("source_content")
            ),
            None,
        )
        if source_content is None:
            raise RuntimeError("migration source content snapshot is missing; explicit recovery is required")
        version = await self.session.get(KnowledgeDocumentVersion, document.primary_version_id)
        entries = list(
            (
                await self.session.exec(
                    select(KnowledgeFile)
                    .where(
                        KnowledgeFile.reference_document_id == document_id,
                        KnowledgeFile.entry_status == "active",
                        col(KnowledgeFile.entry_type).in_({"manager", "publish", "share"}),
                    )
                    .order_by(KnowledgeFile.id)
                    .with_for_update()
                )
            ).all()
        )
        if version is None or not entries:
            raise RuntimeError("migration destination has no primary version or active entries")
        if any(entry.projection_lease_owner for entry in entries):
            raise RuntimeError("migration destination has an active projection lease")
        return {
            "tenant_id": int(batch.tenant_id),
            "document_id": int(document_id),
            "manager_knowledge_id": int(document.knowledge_id),
            "deleted_document_ids": deleted_document_ids,
            "source_content": source_content,
            "target_content": {
                "document_id": int(document.id),
                "version_id": int(version.id),
                "file_id": int(version.knowledge_file_id),
                "generation": int(document.content_generation),
            },
            "knowledge_ids": tuple(sorted({int(entry.knowledge_id) for entry in entries})),
            "membership_generation": max(
                int(document.content_generation), *(int(entry.desired_entry_generation) for entry in entries)
            ),
            "entries": [
                (int(entry.id), int(entry.desired_content_generation), int(entry.desired_entry_generation))
                for entry in entries
            ],
            "ready": all(
                entry.projection_status == "ready"
                and entry.applied_content_generation >= document.content_generation
                and entry.applied_entry_generation >= entry.desired_entry_generation
                for entry in entries
            ),
        }

    async def finish_shared_projection(
        self, unit_id: int, plan: dict, *, attempt_id: int, execution_token: str
    ) -> None:
        fresh = await self.shared_projection_plan(unit_id, attempt_id=attempt_id, execution_token=execution_token)
        if any(
            fresh[key] != plan[key] for key in ("target_content", "knowledge_ids", "membership_generation", "entries")
        ):
            raise RuntimeError("migration destination changed during metadata projection")
        for entry_id, content_generation, entry_generation in plan["entries"]:
            entry = await self.session.get(KnowledgeFile, entry_id)
            entry.applied_content_generation = content_generation
            entry.applied_entry_generation = entry_generation
            entry.projection_status = KnowledgeFileProjectionStatus.READY.value
            entry.projection_next_retry_at = None
            entry.projection_retry_count = 0
            entry.projection_last_error = None
            entry.projection_previous_file_id = None
            self.session.add(entry)
        await self._commit()

    async def prepare_preserve_link_folders(self, unit_id: int, *, attempt_id: int, execution_token: str):
        batch, unit, files = await self._active_control_rows(
            unit_id=unit_id, attempt_id=attempt_id, execution_token=execution_token,
        )
        target = await self.session.get(Knowledge, batch.target_space_id)
        owner = await self.session.get(User, target.user_id) if target is not None else None
        if owner is None or owner.delete:
            raise RuntimeError("target knowledge-space owner is disabled or missing")
        folder_id, _parent_path, _, mapping = await self._prepare_target_folder(batch, unit, owner)
        await self._snapshot_source_content(unit, files)
        unit.planned_target_folder_id = folder_id
        unit.folder_mapping_snapshot = mapping
        for row in files:
            row.target_folder_id = folder_id
            self.session.add(row)
        self.session.add(unit)
        await self._commit()
        folder_ids = [int(item["target_folder_id"]) for item in mapping if item["action"] == "created"]
        folders = list((await self.session.exec(select(KnowledgeFile).where(col(KnowledgeFile.id).in_(folder_ids)))).all()) if folder_ids else []
        return folders, int(owner.user_id), int(batch.target_space_id)

    async def record_preserve_link_result(self, unit_id: int, result, *, attempt_id: int, execution_token: str) -> None:
        _, unit, files = await self._active_control_rows(
            unit_id=unit_id, attempt_id=attempt_id, execution_token=execution_token,
        )
        unit.target_document_id = int(result.document_id)
        unit.checkpoint = KnowledgeMigrationCheckpoint.DB_SWITCHED.value
        for row in files:
            row.target_file_id = row.source_file_id
            row.checkpoint = KnowledgeMigrationCheckpoint.DB_SWITCHED.value
            row.target_resource_manifest = {**(row.target_resource_manifest or {}),
                "publish_entry_id": int(result.publish_entry_id), "storage_contract": "shared"}
            self.session.add(row)
        self.session.add(unit)
        await self._commit()

    async def cleanup_source_rows(self, unit_id: int) -> None:
        batch, _, control_files = await self._control_rows(
            unit_id,
            for_update=True,
        )
        source_ids = {row.source_file_id for row in control_files if row.source_file_id != row.target_file_id}
        source_space_ids = {row.source_space_id for row in control_files}
        await self.session.exec(
            delete(KnowledgeFilePdfArtifact).where(
                col(KnowledgeFilePdfArtifact.knowledge_file_id).in_(source_ids)
            )
        )
        await self.session.exec(
            delete(KnowledgeFile).where(col(KnowledgeFile.id).in_(source_ids))
        )
        spaces = list(
            (
                await self.session.exec(
                    select(Knowledge).where(
                        col(Knowledge.id).in_(
                            source_space_ids | {batch.target_space_id}
                        )
                    )
                )
            ).all()
        )
        for space in spaces:
            space.update_time = datetime.now()
            self.session.add(space)
        await self._commit()

    async def cleanup_new_target_rows(
        self,
        unit_id: int,
        *,
        attempt_id: int,
        execution_token: str,
    ) -> None:
        _, unit, control_files = await self._active_control_rows(
            unit_id=unit_id,
            attempt_id=attempt_id,
            execution_token=execution_token,
        )
        target_ids = {
            int(row.target_file_id)
            for row in control_files
            if row.target_file_id is not None and row.target_file_id != row.source_file_id
        }
        if target_ids:
            await self.session.exec(
                delete(KnowledgeFilePdfArtifact).where(
                    col(KnowledgeFilePdfArtifact.knowledge_file_id).in_(
                        target_ids
                    )
                )
            )
            await self.session.exec(
                delete(KnowledgeFile).where(col(KnowledgeFile.id).in_(target_ids))
            )
        created_folder_ids = [
            int(item["target_folder_id"])
            for item in unit.folder_mapping_snapshot or []
            if item.get("action") == "created"
            and item.get("target_folder_id") is not None
        ]
        for folder_id in reversed(created_folder_ids):
            folder = (
                await self.session.exec(
                    select(KnowledgeFile).where(KnowledgeFile.id == folder_id)
                )
            ).first()
            if folder is None:
                continue
            child_path = f"{folder.file_level_path or ''}/{folder.id}"
            has_child = (
                await self.session.exec(
                    select(KnowledgeFile.id)
                    .where(KnowledgeFile.file_level_path == child_path)
                    .limit(1)
                )
            ).first()
            if has_child is None:
                await self.session.delete(folder)
        for control in control_files:
            control.target_file_id = None
            control.target_folder_id = None
            control.target_resource_manifest = None
            self.session.add(control)
        unit.planned_target_folder_id = None
        unit.folder_mapping_snapshot = [
            {
                **item,
                "target_folder_id": None
                if item.get("action") == "created"
                else item.get("target_folder_id"),
                "action": "planned"
                if item.get("action") == "created"
                else item.get("action"),
            }
            for item in unit.folder_mapping_snapshot or []
        ]
        self.session.add(unit)
        await self._commit()
