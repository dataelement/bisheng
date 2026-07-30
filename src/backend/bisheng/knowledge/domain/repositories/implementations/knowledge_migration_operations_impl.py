"""跨知识库迁移对现有存储、索引、标签与权限能力的生产适配器。"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path

from sqlmodel import col, select

from bisheng.api.services.knowledge_imp import (
    delete_minio_file_snapshot_objects,
    delete_minio_files,
    delete_vector_files,
)
from bisheng.core.ai import FakeEmbeddings
from bisheng.core.database import get_async_db_session
from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync
from bisheng.database.models.review_tags import ReviewTagDao
from bisheng.database.models.tag import ResourceTypeEnum, TagDao
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_file_pdf_artifact import (
    KnowledgeFilePdfArtifact,
)
from bisheng.knowledge.domain.models.knowledge_migration import (
    KnowledgeMigrationFile,
    KnowledgeMigrationUnit,
    KnowledgeMigrationUnitStatus,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_migration_runtime_repository_impl import (
    KnowledgeMigrationRuntimeRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_migration_runtime_repository import (
    MigrationRuntimeContext,
)
from bisheng.knowledge.domain.services.file_migration.executor import (
    MigrationExecutionUnit,
)
from bisheng.knowledge.domain.services.knowledge_utils import KnowledgeUtils
from bisheng.permission.domain.schemas.tuple_operation import TupleOperation
from bisheng.permission.domain.services.permission_service import PermissionService
from bisheng.worker.knowledge.file_worker import copy_vector


def _storage_object_names(file: KnowledgeFile) -> dict[str, str]:
    metadata = file.user_metadata or {}
    return {
        "original": str(
            KnowledgeUtils.resolve_source_object_name(
                int(file.id or 0),
                file.file_name,
                file.object_name,
            )
            or ""
        ),
        "converted": str(file.id or ""),
        "bbox": str(file.bbox_object_name or ""),
        "preview": str(
            KnowledgeUtils.resolve_preview_object_name(
                int(file.id or 0),
                file.file_name,
                file.preview_file_object_name,
            )
            or ""
        ),
        "thumbnail": str(file.thumbnails or ""),
        "pdf_preview": str(metadata.get("pdf_preview_object_name") or ""),
    }


def _target_object_names(
    source: KnowledgeFile,
    target: KnowledgeFile,
) -> dict[str, str]:
    source_names = _storage_object_names(source)
    preview = KnowledgeUtils.get_knowledge_preview_file_object_name(
        int(target.id or 0),
        target.file_name,
    )
    if not preview and source_names["preview"]:
        preview = f"preview/{target.id}{Path(source_names['preview']).suffix}"
    thumbnail = ""
    if source_names["thumbnail"]:
        thumbnail = (
            f"migration/thumbnails/{target.id}"
            f"{Path(source_names['thumbnail']).suffix}"
        )
    return {
        "original": KnowledgeUtils.get_knowledge_file_object_name(
            int(target.id or 0),
            target.file_name,
        ),
        "converted": str(target.id or ""),
        "bbox": (
            KnowledgeUtils.get_knowledge_bbox_file_object_name(int(target.id or 0))
            if source_names["bbox"]
            else ""
        ),
        "preview": str(preview or ""),
        "thumbnail": thumbnail,
        "pdf_preview": (
            KnowledgeUtils.get_knowledge_pdf_preview_file_object_name(
                int(target.id or 0)
            )
            if source_names["pdf_preview"]
            else ""
        ),
    }


def _copy_object_if_present(source_name: str, target_name: str) -> bool:
    if not source_name or not target_name:
        return False
    client = get_minio_storage_sync()
    if not client.object_exists_sync(client.bucket, source_name):
        return False
    if not client.object_exists_sync(client.bucket, target_name):
        client.copy_object_sync(
            source_bucket=client.bucket,
            source_object=source_name,
            dest_bucket=client.bucket,
            dest_object=target_name,
        )
    return True


def _storage_exists(object_names: dict[str, str]) -> dict[str, bool]:
    client = get_minio_storage_sync()
    return {
        key: bool(name)
        and bool(client.object_exists_sync(client.bucket, name))
        for key, name in object_names.items()
    }


def _count_milvus_records(space: Knowledge, file_id: int) -> int:
    store = KnowledgeRag.init_knowledge_milvus_vectorstore_sync(
        0,
        knowledge=space,
        embeddings=FakeEmbeddings(),
    )
    if store.col is None:
        return 0
    expression = f"document_id=={file_id} && knowledge_id=={space.id}"
    if hasattr(store.col, "query_iterator"):
        iterator = store.col.query_iterator(
            expr=expression,
            output_fields=["pk"],
            batch_size=1000,
        )
        count = 0
        try:
            while True:
                rows = iterator.next()
                if not rows:
                    break
                count += len(rows)
        finally:
            iterator.close()
        return count
    return len(
        store.col.query(
            expr=expression,
            output_fields=["pk"],
            limit=16384,
        )
    )


def _count_es_records(space: Knowledge, file_id: int) -> int:
    store = KnowledgeRag.init_knowledge_es_vectorstore_sync(knowledge=space)
    if store is None or not store.client.indices.exists(index=space.index_name):
        return 0
    response = store.client.count(
        index=space.index_name,
        query={
            "bool": {
                "filter": [
                    {"term": {"metadata.document_id": file_id}},
                ]
            }
        },
    )
    return int(response.get("count", 0))


async def _index_counts(space: Knowledge, file_id: int) -> dict[str, int]:
    milvus, elasticsearch = await asyncio.gather(
        asyncio.to_thread(_count_milvus_records, space, file_id),
        asyncio.to_thread(_count_es_records, space, file_id),
    )
    return {"milvus": milvus, "elasticsearch": elasticsearch}


async def _tag_ids(file_id: int, tenant_id: int) -> dict[str, list[int]]:
    resource_id = str(file_id)
    approved = await TagDao.aget_resource_tag_ids_batch(
        [resource_id],
        ResourceTypeEnum.SPACE_FILE,
    )
    pending = await asyncio.to_thread(
        ReviewTagDao.get_tags_by_resource_batch,
        [ResourceTypeEnum.SPACE_FILE],
        [resource_id],
        tenant_id=tenant_id,
    )
    return {
        "approved": sorted(
            {int(value) for value in approved.get(resource_id, [])}
        ),
        "pending": sorted(
            {
                int(tag.id)
                for tag in pending.get(resource_id, [])
                if tag.id is not None
                and int(getattr(tag, "review_status", 0)) == 0
            }
        ),
    }


async def _replace_tags(
    file_id: int,
    *,
    owner_id: int,
    tenant_id: int,
    tag_ids: dict[str, list[int]],
) -> None:
    resource_id = str(file_id)
    await TagDao.aupdate_resource_tags(
        tag_ids.get("approved", []),
        resource_id,
        ResourceTypeEnum.SPACE_FILE,
        owner_id,
    )
    await ReviewTagDao.aupdate_resource_tags(
        tag_ids.get("pending", []),
        resource_id,
        ResourceTypeEnum.SPACE_FILE,
        owner_id,
        tenant_id=tenant_id,
    )


async def _read_permission_tuples(
    object_ref: str,
) -> tuple[dict[str, str], ...]:
    fga = PermissionService._get_fga()
    if fga is None:
        raise RuntimeError("OpenFGA is unavailable")
    rows = await fga.read_tuples(object=object_ref)
    return tuple(
        {
            "user": str(row["user"]),
            "relation": str(row["relation"]),
            "object": str(row["object"]),
        }
        for row in (rows or [])
    )


async def _replace_permission_tuples(
    object_ref: str,
    desired: Sequence[dict[str, str]],
) -> None:
    current = await _read_permission_tuples(object_ref)
    operations = [
        TupleOperation(
            action="delete",
            user=row["user"],
            relation=row["relation"],
            object=row["object"],
        )
        for row in current
    ]
    operations.extend(
        TupleOperation(
            action="write",
            user=row["user"],
            relation=row["relation"],
            object=row["object"],
        )
        for row in desired
    )
    await PermissionService.batch_write_tuples(
        operations,
        crash_safe=True,
        raise_on_failure=True,
        stop_on_failure=True,
    )


def _parent_subject(file: KnowledgeFile, target_space_id: int) -> str:
    path_ids = [
        int(part)
        for part in (file.file_level_path or "").split("/")
        if part.isdigit()
    ]
    if path_ids:
        return f"folder:{path_ids[-1]}"
    return f"knowledge_space:{target_space_id}"


def _target_permissions(
    file: KnowledgeFile,
    *,
    target_space_id: int,
    owner_id: int,
    object_type: str = "knowledge_file",
) -> tuple[dict[str, str], ...]:
    object_ref = f"{object_type}:{file.id}"
    return (
        {
            "user": f"user:{owner_id}",
            "relation": "owner",
            "object": object_ref,
        },
        {
            "user": _parent_subject(file, target_space_id),
            "relation": "parent",
            "object": object_ref,
        },
    )


class KnowledgeMigrationOperationsImpl:
    """按持久 target ID 执行可重投的迁移外部操作。"""

    @staticmethod
    async def _load_context(unit_id: int) -> MigrationRuntimeContext:
        async with get_async_db_session() as session:
            repository = KnowledgeMigrationRuntimeRepositoryImpl(session)
            return await repository.load_context(unit_id)

    async def create_target_rows(self, unit: MigrationExecutionUnit) -> None:
        if unit.attempt_id is None or not unit.execution_token:
            raise RuntimeError("migration execution generation is missing")
        async with get_async_db_session() as session:
            repository = KnowledgeMigrationRuntimeRepositoryImpl(session)
            await repository.prepare_target_rows(
                unit.unit_id,
                attempt_id=unit.attempt_id,
                execution_token=unit.execution_token,
            )

    async def copy_target_objects(self, unit: MigrationExecutionUnit) -> None:
        copy_jobs: list[
            tuple[dict[str, str], dict[str, str], dict[str, bool]]
        ] = []
        async with get_async_db_session() as session:
            repository = KnowledgeMigrationRuntimeRepositoryImpl(session)
            context = await repository.load_context(unit.unit_id)
            for item in context.files:
                source_names = _storage_object_names(item.source)
                target_names = _target_object_names(item.source, item.target)
                source_exists = await asyncio.to_thread(
                    _storage_exists,
                    source_names,
                )
                item.target.object_name = (
                    target_names["original"]
                    if source_exists["original"]
                    else None
                )
                item.target.bbox_object_name = (
                    target_names["bbox"] if source_exists["bbox"] else ""
                )
                item.target.preview_file_object_name = (
                    target_names["preview"]
                    if source_exists["preview"]
                    else None
                )
                item.target.thumbnails = (
                    target_names["thumbnail"]
                    if source_exists["thumbnail"]
                    else None
                )
                metadata = dict(item.target.user_metadata or {})
                if source_exists["pdf_preview"]:
                    metadata["pdf_preview_object_name"] = target_names[
                        "pdf_preview"
                    ]
                else:
                    metadata.pop("pdf_preview_object_name", None)
                    metadata.pop("pdf_preview_source_md5", None)
                item.target.user_metadata = metadata
                artifact = (
                    await session.exec(
                        select(KnowledgeFilePdfArtifact).where(
                            KnowledgeFilePdfArtifact.knowledge_file_id
                            == int(item.target.id)
                        )
                    )
                ).first()
                if artifact is not None:
                    object_mapping = {
                        source_name: target_names[key]
                        for key, source_name in source_names.items()
                        if source_name and target_names[key]
                    }
                    artifact.source_object_name = object_mapping.get(
                        artifact.source_object_name,
                        artifact.source_object_name,
                    )
                    if artifact.object_name:
                        artifact.object_name = object_mapping.get(
                            artifact.object_name,
                            artifact.object_name,
                        )
                    session.add(artifact)
                manifest = dict(item.control.target_resource_manifest or {})
                manifest.update(
                    {
                        "source_objects": source_names,
                        "source_object_exists": source_exists,
                        "target_objects": target_names,
                    }
                )
                item.control.target_resource_manifest = manifest
                session.add(item.target)
                session.add(item.control)
                copy_jobs.append(
                    (source_names, target_names, source_exists)
                )
            await session.commit()
        for source_names, target_names, source_exists in copy_jobs:
            for key, source_name in source_names.items():
                if not source_exists[key]:
                    continue
                copied = await asyncio.to_thread(
                    _copy_object_if_present,
                    source_name,
                    target_names[key],
                )
                if not copied:
                    raise RuntimeError(
                        f"source storage object disappeared during copy: {key}"
                    )

    async def build_target_indexes(self, unit: MigrationExecutionUnit) -> None:
        context = await self._load_context(unit.unit_id)
        for item in context.files:
            source_space = context.source_spaces[int(item.source.knowledge_id)]
            await asyncio.to_thread(
                delete_vector_files,
                [int(item.target.id)],
                context.target_space,
            )
            await asyncio.to_thread(
                copy_vector,
                source_space,
                context.target_space,
                int(item.source.id),
                int(item.target.id),
            )

    async def write_target_permissions(
        self,
        unit: MigrationExecutionUnit,
    ) -> None:
        context = await self._load_context(unit.unit_id)
        owner_id = int(context.target_owner.user_id)
        tag_updates: dict[int, dict[str, list[int]]] = {}
        for folder in context.created_folders:
            await _replace_permission_tuples(
                f"folder:{folder.id}",
                _target_permissions(
                    folder,
                    target_space_id=int(context.target_space.id),
                    owner_id=owner_id,
                    object_type="folder",
                ),
            )
        for item in context.files:
            tags = await _tag_ids(
                int(item.source.id),
                int(context.batch.tenant_id),
            )
            await _replace_tags(
                int(item.target.id),
                owner_id=owner_id,
                tenant_id=int(context.batch.tenant_id),
                tag_ids=tags,
            )
            await _replace_permission_tuples(
                f"knowledge_file:{item.target.id}",
                _target_permissions(
                    item.target,
                    target_space_id=int(context.target_space.id),
                    owner_id=owner_id,
                ),
            )
            tag_updates[int(item.control.id)] = tags
        async with get_async_db_session() as session:
            repository = KnowledgeMigrationRuntimeRepositoryImpl(session)
            fresh = await repository.load_context(unit.unit_id)
            for row in fresh.files:
                control = row.control
                manifest = dict(control.target_resource_manifest or {})
                manifest["tag_ids"] = tag_updates[int(control.id)]
                control.target_resource_manifest = manifest
                session.add(control)
            await session.commit()

    async def verify_target(self, unit: MigrationExecutionUnit) -> None:
        context = await self._load_context(unit.unit_id)
        owner_id = int(context.target_owner.user_id)
        for item in context.files:
            if int(item.target.knowledge_id) != int(context.target_space.id):
                raise RuntimeError("target row belongs to another knowledge space")
            if int(item.target.user_id or 0) != owner_id:
                raise RuntimeError("target row has the wrong owner")
            manifest = item.control.target_resource_manifest or {}
            source_exists = manifest.get("source_object_exists") or {}
            target_objects = manifest.get("target_objects") or {}
            target_exists = await asyncio.to_thread(
                _storage_exists,
                target_objects,
            )
            missing = [
                key
                for key, existed in source_exists.items()
                if existed and not target_exists.get(key, False)
            ]
            if missing:
                raise RuntimeError(
                    f"target storage objects are missing: {sorted(missing)}"
                )
            source_counts, target_counts = await asyncio.gather(
                _index_counts(
                    context.source_spaces[int(item.source.knowledge_id)],
                    int(item.source.id),
                ),
                _index_counts(context.target_space, int(item.target.id)),
            )
            if source_counts != target_counts:
                raise RuntimeError(
                    "target index counts do not match source: "
                    f"source={source_counts}, target={target_counts}"
                )
            expected_tags = manifest.get("tag_ids") or {
                "approved": [],
                "pending": [],
            }
            actual_tags = await _tag_ids(
                int(item.target.id),
                int(context.batch.tenant_id),
            )
            if actual_tags != expected_tags:
                raise RuntimeError("target tags do not match source tags")
            actual_permissions = await _read_permission_tuples(
                f"knowledge_file:{item.target.id}"
            )
            expected_permissions = _target_permissions(
                item.target,
                target_space_id=int(context.target_space.id),
                owner_id=owner_id,
            )
            if not all(row in actual_permissions for row in expected_permissions):
                raise RuntimeError("target owner or parent permission is missing")

    async def switch_database(self, unit: MigrationExecutionUnit) -> None:
        if unit.attempt_id is None or not unit.execution_token:
            raise RuntimeError("migration execution generation is missing")
        async with get_async_db_session() as session:
            repository = KnowledgeMigrationRuntimeRepositoryImpl(session)
            await repository.activate_switch(
                unit.unit_id,
                attempt_id=unit.attempt_id,
                execution_token=unit.execution_token,
            )

    async def cleanup_source_external(
        self,
        unit: MigrationExecutionUnit,
    ) -> None:
        context = await self._load_context(unit.unit_id)
        for item in context.files:
            source_space = context.source_spaces[int(item.source.knowledge_id)]
            await asyncio.to_thread(
                delete_vector_files,
                [int(item.source.id)],
                source_space,
            )
            await asyncio.to_thread(delete_minio_files, item.source)
            await _replace_tags(
                int(item.source.id),
                owner_id=int(
                    item.source.user_id or context.target_owner.user_id
                ),
                tenant_id=int(context.batch.tenant_id),
                tag_ids={"approved": [], "pending": []},
            )
            await _replace_permission_tuples(
                f"knowledge_file:{item.source.id}",
                (),
            )

        overwrite_items = (
            context.unit.overwrite_snapshot or {}
        ).get("target_files") or []
        if overwrite_items:
            overwrite_ids = [
                int(item["record"]["id"]) for item in overwrite_items
            ]
            await asyncio.to_thread(
                delete_vector_files,
                overwrite_ids,
                context.target_space,
            )
            await asyncio.to_thread(
                delete_minio_file_snapshot_objects,
                [item["record"] for item in overwrite_items],
                (
                    context.unit.overwrite_snapshot or {}
                ).get("pdf_artifacts") or [],
            )
            for overwrite_id in overwrite_ids:
                await _replace_tags(
                    overwrite_id,
                    owner_id=int(context.target_owner.user_id),
                    tenant_id=int(context.batch.tenant_id),
                    tag_ids={"approved": [], "pending": []},
                )
                await _replace_permission_tuples(
                    f"knowledge_file:{overwrite_id}",
                    (),
                )

    async def cleanup_source_rows(
        self,
        unit: MigrationExecutionUnit,
    ) -> None:
        async with get_async_db_session() as session:
            repository = KnowledgeMigrationRuntimeRepositoryImpl(session)
            await repository.cleanup_source_rows(unit.unit_id)

    async def cleanup_new_target(
        self,
        unit: MigrationExecutionUnit,
    ) -> None:
        if unit.attempt_id is None or not unit.execution_token:
            raise RuntimeError("migration execution generation is missing")
        try:
            context = await self._load_context(unit.unit_id)
        except RuntimeError as exc:
            if "target rows have not been prepared" in str(exc):
                return
            raise
        for item in context.files:
            await asyncio.to_thread(
                delete_vector_files,
                [int(item.target.id)],
                context.target_space,
            )
            await asyncio.to_thread(delete_minio_files, item.target)
            await _replace_tags(
                int(item.target.id),
                owner_id=int(context.target_owner.user_id),
                tenant_id=int(context.batch.tenant_id),
                tag_ids={"approved": [], "pending": []},
            )
            await _replace_permission_tuples(
                f"knowledge_file:{item.target.id}",
                (),
            )
        for folder in context.created_folders:
            await _replace_permission_tuples(f"folder:{folder.id}", ())
        async with get_async_db_session() as session:
            repository = KnowledgeMigrationRuntimeRepositoryImpl(session)
            await repository.cleanup_new_target_rows(
                unit.unit_id,
                attempt_id=unit.attempt_id,
                execution_token=unit.execution_token,
            )

    async def cleanup_empty_source_folders(self, batch_id: int) -> None:
        """仅清理由成功单元影响且此刻确实为空的来源目录。"""

        async with get_async_db_session() as session:
            units = list(
                (
                    await session.exec(
                        select(KnowledgeMigrationUnit).where(
                            KnowledgeMigrationUnit.batch_id == batch_id,
                            KnowledgeMigrationUnit.status
                            == KnowledgeMigrationUnitStatus.SUCCEEDED.value,
                        )
                    )
                ).all()
            )
            unit_ids = {int(unit.id) for unit in units}
            file_rows = []
            if unit_ids:
                file_rows = list(
                    (
                        await session.exec(
                            select(KnowledgeMigrationFile).where(
                                col(KnowledgeMigrationFile.unit_id).in_(
                                    unit_ids
                                )
                            )
                        )
                    ).all()
                )
            candidate_ids = {
                int(item["source_folder_id"])
                for unit in units
                for item in unit.folder_mapping_snapshot or []
                if item.get("source_folder_id") is not None
            }
            candidate_ids.update(
                int(unit.source_parent_folder_id)
                for unit in units
                if unit.source_parent_folder_id is not None
            )
            candidate_ids.update(
                int(row.source_folder_id)
                for row in file_rows
                if row.source_folder_id is not None
            )
            candidate_ids.update(
                int(folder_id)
                for row in file_rows
                for folder_id in (
                    row.source_resource_manifest or {}
                ).get("source_folder_ids", [])
            )
            if not candidate_ids:
                return
            folders = list(
                (
                    await session.exec(
                        select(KnowledgeFile).where(
                            col(KnowledgeFile.id).in_(candidate_ids)
                        )
                    )
                ).all()
            )
            folders.sort(
                key=lambda folder: int(folder.level or 0),
                reverse=True,
            )
            for folder in folders:
                child_path = f"{folder.file_level_path or ''}/{folder.id}"
                child = (
                    await session.exec(
                        select(KnowledgeFile.id)
                        .where(
                            KnowledgeFile.knowledge_id == folder.knowledge_id,
                            KnowledgeFile.file_level_path == child_path,
                        )
                        .limit(1)
                    )
                ).first()
                if child is not None:
                    continue
                await _replace_permission_tuples(f"folder:{folder.id}", ())
                await session.delete(folder)
                await session.flush()
            await session.commit()
