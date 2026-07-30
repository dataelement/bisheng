from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import or_
from sqlmodel import col, delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.knowledge import Knowledge
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
from bisheng.share_link.domain.models.share_link import (
    ResourceTypeEnum as ShareResourceTypeEnum,
)
from bisheng.share_link.domain.models.share_link import ShareLink
from bisheng.user.domain.models.user import User


class KnowledgeMigrationRuntimeRepositoryImpl(KnowledgeMigrationRuntimeRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

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
                await self.session.exec(
                    select(KnowledgeFile).where(col(KnowledgeFile.id).in_(source_ids))
                )
            ).all()
        }
        target_files = {
            int(row.id): row
            for row in (
                await self.session.exec(
                    select(KnowledgeFile).where(col(KnowledgeFile.id).in_(target_ids))
                )
            ).all()
        }
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
                action = "reused"
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
            str(space.model or "") != str(target_space.model or "")
            for space in source_spaces
        ):
            raise RuntimeError(
                "source and target embedding models are no longer compatible"
            )
        source_artifacts = list(
            (
                await self.session.exec(
                    select(KnowledgeFilePdfArtifact).where(
                        col(KnowledgeFilePdfArtifact.knowledge_file_id).in_(
                            source_ids
                        )
                    )
                )
            ).all()
        )
        artifacts_by_source = {
            int(artifact.knowledge_file_id): artifact
            for artifact in source_artifacts
        }
        for control in control_files:
            source = sources[control.source_file_id]
            target = self._target_file_clone(
                source,
                batch=batch,
                owner=owner,
                parent_path=parent_path,
                level=level,
            )
            self.session.add(target)
            await self.session.flush()
            control.target_file_id = int(target.id)
            control.target_folder_id = target_folder_id
            control.target_resource_manifest = {
                "target_file_level_path": parent_path,
                "created_folder_ids": [
                    int(item["target_folder_id"])
                    for item in mapping
                    if item["action"] == "created"
                ],
            }
            self.session.add(control)
            source_artifact = artifacts_by_source.get(control.source_file_id)
            if source_artifact is not None:
                artifact_payload = source_artifact.model_dump()
                artifact_payload.pop("id", None)
                artifact_payload.pop("create_time", None)
                artifact_payload.pop("update_time", None)
                artifact_payload["knowledge_file_id"] = int(target.id)
                self.session.add(KnowledgeFilePdfArtifact(**artifact_payload))
        unit.planned_target_folder_id = target_folder_id
        unit.folder_mapping_snapshot = mapping
        self.session.add(unit)
        await self.session.commit()
        return await self.load_context(unit_id)

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
        await self._validate_current_conflicts(
            batch=batch,
            unit=unit,
            sources=sources,
            targets=targets,
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
            for version in versions:
                version.knowledge_file_id = target_id_by_source[
                    int(version.knowledge_file_id)
                ]
                self.session.add(version)
            document.knowledge_id = batch.target_space_id
            document.file_level_path = (
                next(iter(target_by_id.values())).file_level_path or ""
            )
            document.level = next(iter(target_by_id.values())).level
            self.session.add(document)
        for control in control_files:
            source = source_by_id[control.source_file_id]
            target = target_by_id[int(control.target_file_id)]
            target.status = KnowledgeFileStatus.SUCCESS.value
            if source.entry_type == KnowledgeFileEntryType.MANAGER.value:
                target.reference_document_id = source.reference_document_id
                target.entry_type = KnowledgeFileEntryType.MANAGER.value
                target.entry_status = KnowledgeFileEntryStatus.ACTIVE.value
                source.entry_status = KnowledgeFileEntryStatus.DELETING.value
            source.status = KnowledgeFileStatus.PROCESSING.value
            self.session.add(source)
            self.session.add(target)
        unit.checkpoint = KnowledgeMigrationCheckpoint.DB_SWITCHED.value
        self.session.add(unit)
        for control in control_files:
            control.checkpoint = KnowledgeMigrationCheckpoint.DB_SWITCHED.value
            self.session.add(control)
        await self.session.commit()

    async def cleanup_source_rows(self, unit_id: int) -> None:
        batch, _, control_files = await self._control_rows(
            unit_id,
            for_update=True,
        )
        source_ids = {row.source_file_id for row in control_files}
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
        await self.session.commit()

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
        target_ids = {int(row.target_file_id) for row in control_files if row.target_file_id is not None}
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
        await self.session.commit()
