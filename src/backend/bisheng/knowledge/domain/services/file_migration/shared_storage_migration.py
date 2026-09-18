"""F4: Shared-storage migration coordinator.

Orchestrates the tenant migration from per-space storage to the shared
Milvus collection / ES index. The migration is a three-phase process:

  1. TENANT_WRITE_FROZEN — freeze writes and verify no in-flight projections
  2. TENANT_COPYING — copy vectors from per-space collections to the shared store
  3. TENANT_WRITE_RESUMED — unfreeze writes and activate the routing switch

Each phase is idempotent; the coordinator can be safely re-run on failure.

运行时仅支持共享存储；此工具只保留历史数据的正向迁移。
迁移失败保持冻结，不提供恢复旧路由的开关。
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlmodel import col, select

from bisheng.knowledge.domain.models.knowledge import KnowledgeDao, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_space_shared_storage import (
    KnowledgeSpaceSharedStorageRoutingDao,
)
from bisheng.knowledge.domain.services.file_migration.state import MigrationScope
from bisheng.knowledge.rag.shared_space_storage import (
    SharedSpaceStorageReader,
    freeze_tenant_writes,
    unfreeze_tenant_writes,
)

logger = logging.getLogger(__name__)

# Labels written to the ``migration_state`` column of the routing table.
MIGRATION_STATE_IDLE = ""
MIGRATION_STATE_FROZEN = "TENANT_WRITE_FROZEN"
MIGRATION_STATE_COPYING = "TENANT_COPYING"
MIGRATION_STATE_RESUMED = "TENANT_WRITE_RESUMED"
MIGRATION_STATE_FAILED = "TENANT_MIGRATION_FAILED"


@dataclass
class SharedStorageMigrationProgress:
    tenant_id: int
    scope: MigrationScope = MigrationScope.SHARED_STORAGE
    phase: str = MIGRATION_STATE_IDLE
    total_spaces: int = 0
    migrated_spaces: int = 0
    failed_spaces: int = 0
    errors: list[str] = field(default_factory=list)
    collection_name: str | None = None
    index_name: str | None = None
    embedding_model_id: int | None = None
    schema_fingerprint: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class SharedStorageMigrationCoordinator:
    """F4: Tenant migration coordinator for shared SPACE storage.

    Usage::

        coordinator = SharedStorageMigrationCoordinator()
        progress = await coordinator.migrate_tenant(tenant_id=1)
    """

    def __init__(self) -> None:
        self._reader: SharedSpaceStorageReader | None = None

    @staticmethod
    async def _list_tenant_spaces(tenant_id: int) -> list[Any]:
        tenant_loader = getattr(KnowledgeDao, "aget_spaces_by_tenant", None)
        if tenant_loader is not None:
            return list(await tenant_loader(int(tenant_id)))
        all_spaces = await KnowledgeDao.aget_all_knowledge(
            knowledge_type=KnowledgeTypeEnum.SPACE,
        )
        return [
            space
            for space in all_spaces
            if int(getattr(space, "tenant_id", None) or 1) == int(tenant_id)
        ]

    async def migrate_tenant(
        self,
        tenant_id: int,
        *,
        collection_name: str | None = None,
        index_name: str | None = None,
        embedding_model_id: int | None = None,
        dry_run: bool = False,
    ) -> SharedStorageMigrationProgress:
        progress = SharedStorageMigrationProgress(
            tenant_id=tenant_id,
            started_at=datetime.now(timezone.utc),
        )

        try:
            progress.phase = MIGRATION_STATE_FROZEN
            await self._phase_freeze(tenant_id, progress, dry_run=dry_run)

            progress.phase = MIGRATION_STATE_COPYING
            await self._phase_copy(
                tenant_id,
                progress,
                collection_name=collection_name,
                index_name=index_name,
                embedding_model_id=embedding_model_id,
                dry_run=dry_run,
            )

            progress.phase = MIGRATION_STATE_RESUMED
            await self._phase_resume(
                tenant_id,
                progress,
                collection_name=collection_name,
                index_name=index_name,
                embedding_model_id=embedding_model_id,
                dry_run=dry_run,
            )
        except Exception:
            progress.phase = MIGRATION_STATE_FAILED
            progress.errors.append(_sanitize_error())
            if not dry_run:
                KnowledgeSpaceSharedStorageRoutingDao.set_migration_state(
                    tenant_id, MIGRATION_STATE_FAILED
                )
            raise

        progress.completed_at = datetime.now(timezone.utc)
        return progress

    async def _phase_freeze(
        self,
        tenant_id: int,
        progress: SharedStorageMigrationProgress,
        *,
        dry_run: bool,
    ) -> None:
        if dry_run:
            logger.info("shared_storage_migration dry_run freeze tenant=%s", tenant_id)
            return
        KnowledgeSpaceSharedStorageRoutingDao.ensure_row(tenant_id)
        KnowledgeSpaceSharedStorageRoutingDao.set_migration_state(
            tenant_id, MIGRATION_STATE_FROZEN
        )
        freeze_tenant_writes(tenant_id)
        logger.info("shared_storage_migration_frozen tenant=%s", tenant_id)

    async def _phase_copy(
        self,
        tenant_id: int,
        progress: SharedStorageMigrationProgress,
        *,
        collection_name: str | None,
        index_name: str | None,
        embedding_model_id: int | None,
        dry_run: bool,
    ) -> None:
        # Discover all SPACE-type knowledge bases in the tenant.
        # KnowledgeDao does not expose a tenant-scoped query; we use the
        # type-filtered paginated list and filter by tenant_id in memory.
        spaces = await self._list_tenant_spaces(tenant_id)
        progress.total_spaces = len(spaces)

        if dry_run:
            logger.info(
                "shared_storage_migration dry_run copy tenant=%s spaces=%d",
                tenant_id,
                len(spaces),
            )
            progress.migrated_spaces = len(spaces)
            return
        if not spaces:
            raise RuntimeError(f"tenant {tenant_id} has no SPACE knowledge bases")

        KnowledgeSpaceSharedStorageRoutingDao.set_migration_state(
            tenant_id, MIGRATION_STATE_COPYING
        )
        await self._copy_tenant_documents(
            tenant_id=tenant_id,
            spaces=spaces,
            progress=progress,
            collection_name=collection_name,
            index_name=index_name,
            embedding_model_id=embedding_model_id,
        )
        progress.migrated_spaces = len(spaces)

    async def _copy_tenant_documents(
        self,
        *,
        tenant_id: int,
        spaces: list[Any],
        progress: SharedStorageMigrationProgress,
        collection_name: str | None,
        index_name: str | None,
        embedding_model_id: int | None,
    ) -> None:
        """Bootstrap the shared stores and copy every active canonical primary."""
        from pymilvus import Collection

        from bisheng.core.database import get_async_db_session
        from bisheng.knowledge.domain.contracts.identifiers import (
            CanonicalDocumentId,
            CanonicalVersionId,
            ContentFileId,
            TenantId,
        )
        from bisheng.knowledge.domain.contracts.shared_space_storage import (
            ContentProjectionIdentity,
            ContentUpsertRequest,
            MembershipUpdateRequest,
        )
        from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
        from bisheng.knowledge.domain.models.knowledge_document import (
            KnowledgeDocument,
            KnowledgeDocumentLifecycleStatus,
        )
        from bisheng.knowledge.domain.models.knowledge_document_version import (
            KnowledgeDocumentVersion,
        )
        from bisheng.knowledge.domain.models.knowledge_file import (
            KnowledgeFile,
            KnowledgeFileProjectionStatus,
        )
        from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
            KnowledgeFileRepositoryImpl,
        )
        from bisheng.knowledge.domain.services.shared_space_projection_support import (
            load_shared_content_chunks_from_legacy,
        )
        from bisheng.knowledge.rag.shared_space_storage import (
            MilvusEsSharedSpaceStorageWriter,
            SharedStoreSchemaSpec,
            TenantRoutingSnapshot,
            _ensure_shared_milvus_connection,
            bootstrap_shared_collection,
            ensure_shared_es_index,
            get_shared_storage_conf,
            shared_collection_name,
            shared_index_name,
        )

        conf = get_shared_storage_conf()
        model_ids = {int(space.model) for space in spaces}
        target_model_id = int(
            embedding_model_id
            or conf.tenant_embedding_model_id
            or next(iter(model_ids))
        )
        if model_ids != {target_model_id}:
            raise RuntimeError(
                "shared migration requires every source SPACE to use the target embedding model"
            )

        source_store = KnowledgeRag.init_knowledge_milvus_vectorstore_sync(
            0, knowledge=spaces[0], allow_legacy_space=True
        )
        vector_field = next(
            field for field in source_store.col.schema.fields if field.name == "vector"
        )
        dimension = int(vector_field.params["dim"])
        spec = SharedStoreSchemaSpec(
            embedding_model_id=target_model_id,
            dimension=dimension,
            knowledge_ids_max_capacity=int(conf.knowledge_ids_max_capacity),
        )
        actual_collection = collection_name or shared_collection_name(tenant_id, conf)
        actual_index = index_name or shared_index_name(tenant_id, conf)
        bootstrap = bootstrap_shared_collection(
            spec,
            tenant_id,
            collection_name=actual_collection,
        )
        es_store = KnowledgeRag.init_es_vectorstore_sync(index_name=actual_index)
        ensure_shared_es_index(
            es_store.client,
            tenant_id,
            conf=conf,
            index_name=actual_index,
        )

        routing_row = KnowledgeSpaceSharedStorageRoutingDao.get_by_tenant(tenant_id)
        if routing_row is None:
            raise RuntimeError("shared migration routing row disappeared")
        snapshot = TenantRoutingSnapshot(
            tenant_id=tenant_id,
            shared_enabled=False,
            routing_version=int(routing_row.routing_version),
            write_frozen=True,
            collection_name=actual_collection,
            index_name=actual_index,
            embedding_model_id=target_model_id,
            schema_fingerprint=bootstrap.fingerprint,
            migration_state=MIGRATION_STATE_COPYING,
        )
        collection = Collection(
            actual_collection, using=_ensure_shared_milvus_connection()
        )
        writer = MilvusEsSharedSpaceStorageWriter(
            tenant_id=tenant_id,
            collection=collection,
            es_client=es_store.client,
            expected_routing_version=snapshot.routing_version,
            schema_spec=spec,
            conf=conf,
            routing_provider=lambda _tenant_id: snapshot,
            migration_mode=True,
        )

        space_ids = [int(space.id) for space in spaces]
        async with get_async_db_session() as session:
            result = await session.execute(
                select(KnowledgeDocument).where(
                    KnowledgeDocument.tenant_id == tenant_id,
                    col(KnowledgeDocument.knowledge_id).in_(space_ids),
                    KnowledgeDocument.lifecycle_status
                    == KnowledgeDocumentLifecycleStatus.ACTIVE.value,
                )
            )
            documents = list(result.scalars().all())
            document_ids = [int(document.id) for document in documents]
            file_repo = KnowledgeFileRepositoryImpl(session)
            entries = await file_repo.find_active_entries_for_documents(
                tenant_id=tenant_id,
                document_ids=document_ids,
                knowledge_ids=space_ids,
            )
            entries_by_document: dict[int, list[KnowledgeFile]] = defaultdict(list)
            for entry in entries:
                entries_by_document[int(entry.reference_document_id)].append(entry)

            for document in documents:
                if document.primary_version_id is None:
                    raise RuntimeError(
                        f"document {document.id} has no primary version"
                    )
                version = await session.get(
                    KnowledgeDocumentVersion, int(document.primary_version_id)
                )
                if version is None or int(version.document_id) != int(document.id):
                    raise RuntimeError(
                        f"document {document.id} primary version is inconsistent"
                    )
                content_file = await session.get(
                    KnowledgeFile, int(version.knowledge_file_id)
                )
                if content_file is None:
                    raise RuntimeError(
                        f"document {document.id} content file is missing"
                    )
                memberships = tuple(
                    sorted(
                        {
                            int(entry.knowledge_id)
                            for entry in entries_by_document.get(int(document.id), [])
                        }
                    )
                )
                if not memberships:
                    continue
                chunks = await load_shared_content_chunks_from_legacy(content_file)
                await writer.upsert_content(
                    ContentUpsertRequest(
                        identity=ContentProjectionIdentity(
                            tenant_id=TenantId(tenant_id),
                            canonical_document_id=CanonicalDocumentId(int(document.id)),
                            canonical_version_id=CanonicalVersionId(int(version.id)),
                            content_file_id=ContentFileId(int(content_file.id)),
                            content_generation=int(document.content_generation),
                            embedding_model_id=str(target_model_id),
                        ),
                        knowledge_ids=memberships,
                        chunks=chunks,
                    )
                )
                await writer.update_membership(
                    MembershipUpdateRequest(
                        tenant_id=TenantId(tenant_id),
                        canonical_document_id=CanonicalDocumentId(int(document.id)),
                        knowledge_ids=memberships,
                        membership_generation=max(
                            int(entry.desired_entry_generation)
                            for entry in entries_by_document[int(document.id)]
                        ),
                        content_generation=int(document.content_generation),
                    )
                )
                for entry in entries_by_document.get(int(document.id), []):
                    entry.applied_content_generation = int(document.content_generation)
                    entry.applied_entry_generation = int(entry.desired_entry_generation)
                    entry.projection_status = KnowledgeFileProjectionStatus.READY.value
                    entry.projection_last_error = None
                    session.add(entry)
            await session.commit()

        progress.collection_name = actual_collection
        progress.index_name = actual_index
        progress.embedding_model_id = target_model_id
        progress.schema_fingerprint = bootstrap.fingerprint

    async def _phase_resume(
        self,
        tenant_id: int,
        progress: SharedStorageMigrationProgress,
        *,
        collection_name: str | None,
        index_name: str | None,
        embedding_model_id: int | None,
        dry_run: bool,
    ) -> None:
        if dry_run:
            logger.info("shared_storage_migration dry_run resume tenant=%s", tenant_id)
            return
        if (
            progress.errors
            or progress.failed_spaces
            or progress.migrated_spaces != progress.total_spaces
            or not progress.collection_name
            or not progress.index_name
            or progress.embedding_model_id is None
            or not progress.schema_fingerprint
        ):
            raise RuntimeError("shared migration is incomplete; refusing routing switch")
        switched = KnowledgeSpaceSharedStorageRoutingDao.switch_to_shared(
            tenant_id,
            collection_name=progress.collection_name,
            index_name=progress.index_name,
            embedding_model_id=progress.embedding_model_id,
            schema_fingerprint=progress.schema_fingerprint,
            migration_state=MIGRATION_STATE_RESUMED,
        )
        if not switched:
            raise RuntimeError("shared migration routing switch updated no row")
        unfreeze_tenant_writes(tenant_id)
        logger.info("shared_storage_migration_resumed tenant=%s", tenant_id)


def _sanitize_error() -> str:
    """Return a safe error summary for progress tracking."""
    import traceback

    return traceback.format_exc()[-500:]
