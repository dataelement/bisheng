"""F4: Shared-storage migration coordinator.

Orchestrates the tenant migration from per-space storage to the shared
Milvus collection / ES index. The migration is a three-phase process:

  1. TENANT_WRITE_FROZEN — freeze writes and verify no in-flight projections
  2. TENANT_COPYING — copy vectors from per-space collections to the shared store
  3. TENANT_WRITE_RESUMED — unfreeze writes and activate the routing switch

Each phase is idempotent; the coordinator can be safely re-run on failure.

Reverse migration (``reverse_migrate_tenant``) copies data from the shared
store back to per-space collections and switches routing to legacy. This is
required for a safe rollback because the shared-projection path only writes
to the shared store (per-space collections are NOT updated while
``shared_enabled=True``).
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlmodel import col, select

from bisheng.knowledge.domain.contracts.errors import (
    SharedStorageContractError,
    SharedStorageErrorCode,
)
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

    async def rollback_tenant(self, tenant_id: int) -> SharedStorageMigrationProgress:
        """Roll back a failed migration: revert routing, then unfreeze writes."""
        progress = SharedStorageMigrationProgress(
            tenant_id=tenant_id,
            started_at=datetime.now(timezone.utc),
            phase=MIGRATION_STATE_FAILED,
        )
        try:
            switched = KnowledgeSpaceSharedStorageRoutingDao.switch_to_legacy(tenant_id)
            if not switched:
                raise RuntimeError(f"routing row missing for tenant {tenant_id}")
            unfreeze_tenant_writes(tenant_id)
            logger.info("shared_storage_migration_rollback tenant=%s", tenant_id)
        except Exception:
            logger.exception("shared_storage_migration_rollback_failed tenant=%s", tenant_id)
            progress.errors.append("rollback failed")
        progress.completed_at = datetime.now(timezone.utc)
        return progress

    async def reverse_migrate_tenant(
        self,
        tenant_id: int,
        *,
        dry_run: bool = False,
    ) -> SharedStorageMigrationProgress:
        """Reverse migration: copy data from shared store back to per-space
        collections, then switch routing to legacy.

        This is the data rollback path (spec 7.4): when the shared-storage
        feature is being rolled back, per-space collections must be brought
        up to date with everything that was written to the shared store while
        ``shared_enabled=True``.

        Phases:
          1. TENANT_WRITE_FROZEN — freeze writes
          2. TENANT_REVERSE_COPYING — copy from shared → per-space
          3. TENANT_LEGACY — switch routing to legacy + unfreeze
        """
        MIGRATION_STATE_REVERSE_COPYING = "TENANT_REVERSE_COPYING"
        progress = SharedStorageMigrationProgress(
            tenant_id=tenant_id,
            started_at=datetime.now(timezone.utc),
        )

        # Phase 1: freeze writes
        progress.phase = MIGRATION_STATE_FROZEN
        if dry_run:
            logger.info(
                "shared_storage_reverse_migration dry_run freeze tenant=%s",
                tenant_id,
            )
        else:
            freeze_tenant_writes(tenant_id)
            logger.info(
                "shared_storage_reverse_migration_frozen tenant=%s",
                tenant_id,
            )

        # Phase 2: copy from shared → per-space
        progress.phase = MIGRATION_STATE_REVERSE_COPYING
        try:
            await self._phase_reverse_copy(tenant_id, progress, dry_run=dry_run)
        except Exception:
            progress.phase = MIGRATION_STATE_FAILED
            if not dry_run:
                KnowledgeSpaceSharedStorageRoutingDao.set_migration_state(
                    tenant_id, MIGRATION_STATE_FAILED
                )
            raise

        if progress.failed_spaces or progress.errors:
            progress.phase = MIGRATION_STATE_FAILED
            if not dry_run:
                KnowledgeSpaceSharedStorageRoutingDao.set_migration_state(
                    tenant_id, MIGRATION_STATE_FAILED
                )
            raise RuntimeError(
                "reverse migration copy failed; shared routing remains active and frozen"
            )

        # Phase 3: switch to legacy + unfreeze
        progress.phase = MIGRATION_STATE_FAILED  # transitional
        if dry_run:
            logger.info(
                "shared_storage_reverse_migration dry_run switch tenant=%s",
                tenant_id,
            )
        else:
            KnowledgeSpaceSharedStorageRoutingDao.switch_to_legacy(tenant_id)
            unfreeze_tenant_writes(tenant_id)
            logger.info(
                "shared_storage_reverse_migration_done tenant=%s spaces=%d",
                tenant_id,
                progress.migrated_spaces,
            )

        progress.phase = "TENANT_LEGACY"
        progress.completed_at = datetime.now(timezone.utc)
        return progress

    async def _phase_reverse_copy(
        self,
        tenant_id: int,
        progress: SharedStorageMigrationProgress,
        *,
        dry_run: bool,
    ) -> None:
        """Copy data from shared store back to per-space collections.

        Reads all chunks from the shared Milvus collection (via
        ``SharedSpaceStorageReader``) and writes them to each space's
        per-space Milvus collection and ES index. The per-space collections
        use the existing ``KnowledgeRag`` bootstrap paths.
        """
        from bisheng.knowledge.rag.shared_space_storage import (
            resolve_space_shared_routing,
            shared_collection_name,
            shared_index_name,
        )

        # Discover all SPACE-type knowledge bases in the tenant.
        spaces = await self._list_tenant_spaces(tenant_id)
        progress.total_spaces = len(spaces)

        if dry_run:
            logger.info(
                "shared_storage_reverse_migration dry_run copy tenant=%s spaces=%d",
                tenant_id,
                len(spaces),
            )
            progress.migrated_spaces = len(spaces)
            return

        if not spaces:
            return

        # Verify the shared store is still accessible.
        first_space = spaces[0]
        snapshot = resolve_space_shared_routing(
            tenant_id,
            getattr(first_space, 'type', None),
        )
        if snapshot is None:
            raise SharedStorageContractError(
                SharedStorageErrorCode.ROUTING_NOT_CONFIGURED,
                "shared routing is unavailable for reverse migration",
                tenant_id=tenant_id,
            )

        collection_name = snapshot.collection_name or shared_collection_name(tenant_id)
        index_name = snapshot.index_name or shared_index_name(tenant_id)

        from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
        from bisheng.llm.domain import LLMService

        embeddings = LLMService.get_knowledge_default_embedding(
            0, tenant_id=tenant_id,
        )
        if embeddings is None:
            raise SharedStorageContractError(
                SharedStorageErrorCode.EMBEDDING_MODEL_MISMATCH,
                "shared embedding model is unavailable for reverse migration",
                tenant_id=tenant_id,
            )

        shared_milvus = KnowledgeRag.init_milvus_vectorstore(
            collection_name=collection_name,
            embeddings=embeddings,
        )
        shared_es = KnowledgeRag.init_es_vectorstore_sync(
            index_name=index_name,
        )

        # Process each space: copy chunks from shared → per-space.
        for space in spaces:
            space_id = int(space.id)
            try:
                await self._reverse_copy_space(
                    space=space,
                    space_id=space_id,
                    shared_milvus=shared_milvus,
                    shared_es=shared_es,
                    shared_index_name=index_name,
                    tenant_id=tenant_id,
                )
                progress.migrated_spaces += 1
            except Exception:
                logger.exception(
                    "shared_storage_reverse_copy_failed space=%s",
                    space_id,
                )
                progress.failed_spaces += 1
                progress.errors.append(
                    f"space {space_id}: {_sanitize_error()}",
                )

    async def _reverse_copy_space(
        self,
        space: Any,
        space_id: int,
        shared_milvus: Any,
        shared_es: Any,
        shared_index_name: str,
        tenant_id: int,
    ) -> None:
        """Copy chunks belonging to *space_id* from shared store to per-space
        collections.

        Strategy:
        1. Resolve canonical documents to the active entry ids in this space.
        2. Purge only those F059 entry rows from the legacy stores.
        3. Query shared store for chunks where ``knowledge_ids`` contains
           *space_id*.
        4. Restore the full authoritative chunk set into Milvus and ES.
        """
        from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag

        space_collection = getattr(space, 'collection_name', None)
        if not space_collection:
            return

        entry_by_document, distribution_entry_ids = await self._load_space_entry_maps(
            tenant_id=tenant_id,
            space_id=space_id,
        )

        # --- Initialize and clean only the F059 distribution entries ---
        per_space_milvus = KnowledgeRag.init_knowledge_milvus_vectorstore_sync(
            0, knowledge=space,
        )
        per_space_es = None
        space_index = getattr(space, 'index_name', None)
        if space_index:
            per_space_es = KnowledgeRag.init_es_vectorstore_sync(index_name=space_index)
        await self._purge_distribution_entries_from_legacy(
            per_space_milvus=per_space_milvus,
            per_space_es=per_space_es,
            space_index=space_index,
            entry_ids=distribution_entry_ids,
        )
        existing_map: dict[tuple[int, int], int] = {}
        logger.info(
            "shared_storage_reverse_existing_map space=%s entries=%d",
            space_id,
            len(existing_map),
        )

        # --- Milvus: scan shared store for this space's chunks ---
        if shared_milvus.col is not None:
            try:
                expr = f"ARRAY_CONTAINS(knowledge_ids, {space_id})"
                output_fields = [
                    "pk",
                    "canonical_document_id",
                    "canonical_version_id",
                    "chunk_index",
                    "text",
                    "vector",
                    "content_generation",
                    "membership_generation",
                    "knowledge_ids",
                    "document_name",
                    "abstract",
                    "bbox",
                    "page",
                    "upload_time",
                    "update_time",
                    "uploader",
                    "updater",
                    "user_metadata",
                ]
                total = 0
                skipped = 0
                if hasattr(shared_milvus.col, "query_iterator"):
                    iterator = shared_milvus.col.query_iterator(
                        expr=expr,
                        output_fields=output_fields,
                        batch_size=1000,
                    )
                    while True:
                        batch = iterator.next()
                        if not batch:
                            break
                        written, skipped_batch = await self._write_per_space_milvus_delta(
                            space=space,
                            space_id=space_id,
                            chunks=batch,
                            existing_map=existing_map,
                            per_space_milvus=per_space_milvus,
                            tenant_id=tenant_id,
                            entry_by_document=entry_by_document,
                        )
                        total += written
                        skipped += skipped_batch
                else:
                    results = shared_milvus.col.query(
                        expr=expr,
                        output_fields=output_fields,
                        limit=16384,
                    )
                    if results:
                        written, skipped_batch = await self._write_per_space_milvus_delta(
                            space=space,
                            space_id=space_id,
                            chunks=results,
                            existing_map=existing_map,
                            per_space_milvus=per_space_milvus,
                            tenant_id=tenant_id,
                            entry_by_document=entry_by_document,
                        )
                        total += written
                        skipped += skipped_batch
                logger.info(
                    "shared_storage_reverse_milvus_copied "
                    "space=%s written=%d skipped=%d",
                    space_id,
                    total,
                    skipped,
                )
            except Exception:
                logger.exception(
                    "shared_storage_reverse_milvus_copy_failed space=%s",
                    space_id,
                )
                raise

        # --- ES: copy from shared ES → per-space ES ---
        if space_index and shared_es is not None:
            try:
                await self._reverse_copy_es(
                    shared_es=shared_es,
                    shared_index_name=shared_index_name,
                    per_space_es=per_space_es,
                    space_id=space_id,
                    space_index=space_index,
                    entry_by_document=entry_by_document,
                )
            except Exception:
                logger.exception(
                    "shared_storage_reverse_es_copy_failed space=%s",
                    space_id,
                )
                raise

    @staticmethod
    async def _load_space_entry_maps(
        *, tenant_id: int, space_id: int
    ) -> tuple[dict[int, int], list[int]]:
        """Resolve canonical documents back to their legacy entry file ids."""
        from bisheng.core.database import get_async_db_session
        from bisheng.knowledge.domain.models.knowledge_file import (
            KnowledgeFile,
            KnowledgeFileEntryStatus,
        )

        async with get_async_db_session() as session:
            result = await session.execute(
                select(KnowledgeFile).where(
                    KnowledgeFile.tenant_id == tenant_id,
                    KnowledgeFile.knowledge_id == space_id,
                    KnowledgeFile.reference_document_id.is_not(None),
                )
            )
            entries = list(result.scalars().all())
        distribution_ids = [int(entry.id) for entry in entries]
        active_by_document: dict[int, int] = {}
        for entry in entries:
            if entry.entry_status == KnowledgeFileEntryStatus.ACTIVE.value:
                active_by_document.setdefault(
                    int(entry.reference_document_id), int(entry.id)
                )
        return active_by_document, distribution_ids

    @staticmethod
    async def _purge_distribution_entries_from_legacy(
        *,
        per_space_milvus: Any,
        per_space_es: Any,
        space_index: str | None,
        entry_ids: list[int],
    ) -> None:
        """Remove only F059 distribution rows before an authoritative restore."""
        import asyncio

        if not entry_ids:
            return
        id_list = ", ".join(str(entry_id) for entry_id in sorted(set(entry_ids)))
        if per_space_milvus.col is not None:
            await asyncio.to_thread(
                per_space_milvus.col.delete,
                expr=f"document_id in [{id_list}]",
            )
        if per_space_es is not None and space_index:
            await asyncio.to_thread(
                per_space_es.client.delete_by_query,
                index=space_index,
                query={"terms": {"metadata.document_id": entry_ids}},
            )

    async def _write_per_space_milvus_delta(
        self,
        space: Any,
        space_id: int,
        chunks: list[dict],
        existing_map: dict[tuple[int, int], int],
        per_space_milvus: Any,
        tenant_id: int,
        entry_by_document: dict[int, int],
    ) -> tuple[int, int]:
        """Write the authoritative shared chunks to per-space Milvus.

        Returns ``(written_count, skipped_count)``.
        """
        import asyncio

        if per_space_milvus.col is None:
            return 0, len(chunks)

        # The destination entry rows were purged first; the map only prevents
        # duplicates when a shared iterator repeats a chunk across batches.
        to_write: list[dict] = []
        skipped = 0
        for chunk in chunks:
            doc_id = int(chunk.get("canonical_document_id", 0))
            chunk_idx = int(chunk.get("chunk_index", 0))
            shared_gen = int(chunk.get("content_generation", 0))
            key = (doc_id, chunk_idx)
            existing_gen = existing_map.get(key, -1)
            entry_id = entry_by_document.get(doc_id)
            if entry_id is None:
                skipped += 1
                continue
            if shared_gen > existing_gen:
                row = {
                    "knowledge_id": space_id,
                    "document_id": entry_id,
                    "chunk_index": chunk_idx,
                    "text": chunk.get("text", ""),
                }
                if chunk.get("vector") is None:
                    raise RuntimeError(
                        f"shared chunk {doc_id}/{chunk_idx} has no vector"
                    )
                row["vector"] = chunk["vector"]
                for field_name in (
                    "document_name",
                    "abstract",
                    "bbox",
                    "page",
                    "upload_time",
                    "update_time",
                    "uploader",
                    "updater",
                ):
                    if field_name in chunk:
                        row[field_name] = chunk[field_name]
                user_metadata = (
                    dict(chunk.get("user_metadata"))
                    if isinstance(chunk.get("user_metadata"), dict)
                    else {}
                )
                user_metadata.update(
                    {
                        "canonical_document_id": doc_id,
                        "canonical_version_id": int(
                            chunk.get("canonical_version_id", 0)
                        ),
                        "content_generation": shared_gen,
                        "entry_generation": int(
                            chunk.get("membership_generation", 0)
                        ),
                    }
                )
                row["user_metadata"] = user_metadata
                to_write.append(row)
                # Update the map so subsequent batches for the same space
                # don't rewrite the same chunk.
                existing_map[key] = shared_gen
            else:
                skipped += 1

        if not to_write:
            return 0, skipped

        def _upsert() -> None:
            if per_space_milvus.col is None:
                return
            per_space_milvus.col.upsert(to_write, timeout=60)

        await asyncio.to_thread(_upsert)
        logger.info(
            "shared_storage_reverse_per_space_milvus space=%s written=%d skipped=%d",
            space_id,
            len(to_write),
            skipped,
        )
        return len(to_write), skipped

    async def _reverse_copy_es(
        self,
        shared_es: Any,
        shared_index_name: str,
        per_space_es: Any,
        space_id: int,
        space_index: str,
        entry_by_document: dict[int, int],
    ) -> None:
        """Copy every shared ES document for this space to the legacy index."""
        import asyncio

        try:
            from elasticsearch.helpers import bulk, scan

            def _scan() -> list[dict]:
                return list(
                    scan(
                        shared_es.client,
                        index=shared_index_name,
                        query={
                            "query": {
                                "terms": {
                                    "metadata.knowledge_ids": [space_id]
                                }
                            }
                        },
                        preserve_order=False,
                    )
                )

            hits = await asyncio.to_thread(_scan)
            actions = []
            skipped = 0
            for hit in hits:
                doc = dict(hit["_source"])
                metadata = dict(doc.get("metadata", {}))
                canonical_document_id = int(
                    metadata.get("canonical_document_id", 0) or 0
                )
                entry_id = entry_by_document.get(canonical_document_id)
                if entry_id is None:
                    skipped += 1
                    continue
                chunk_idx = int(metadata.get("chunk_index", 0) or 0)
                metadata["knowledge_id"] = space_id
                metadata["document_id"] = entry_id
                metadata["entry_generation"] = int(
                    metadata.pop("membership_generation", 0) or 0
                )
                metadata.pop("knowledge_ids", None)
                doc["metadata"] = metadata
                actions.append(
                    {
                        "_index": space_index,
                        "_id": f"{entry_id}_{chunk_idx}",
                        "_source": doc,
                    }
                )

            if actions:
                await asyncio.to_thread(
                    bulk,
                    per_space_es.client,
                    actions,
                    refresh=True,
                )
            logger.info(
                "shared_storage_reverse_es_copied space=%s written=%d skipped=%d",
                space_id,
                len(actions),
                skipped,
            )
        except Exception:
            logger.exception(
                "shared_storage_reverse_es_copy_failed space=%s",
                space_id,
            )
            raise

    # ------------------------------------------------------------------
    # phase helpers
    # ------------------------------------------------------------------

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
            0, knowledge=spaces[0]
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
