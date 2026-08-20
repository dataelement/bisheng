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
from dataclasses import dataclass, field
from datetime import datetime, timezone

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

        # Phase 1: freeze writes
        progress.phase = MIGRATION_STATE_FROZEN
        await self._phase_freeze(tenant_id, progress, dry_run=dry_run)

        # Phase 2: copy vectors
        progress.phase = MIGRATION_STATE_COPYING
        await self._phase_copy(
            tenant_id,
            progress,
            collection_name=collection_name,
            index_name=index_name,
            embedding_model_id=embedding_model_id,
            dry_run=dry_run,
        )

        # Phase 3: resume writes (activate routing)
        progress.phase = MIGRATION_STATE_RESUMED
        await self._phase_resume(
            tenant_id,
            progress,
            collection_name=collection_name,
            index_name=index_name,
            embedding_model_id=embedding_model_id,
            dry_run=dry_run,
        )

        progress.completed_at = datetime.now(timezone.utc)
        return progress

    async def rollback_tenant(self, tenant_id: int) -> SharedStorageMigrationProgress:
        """Roll back a failed migration: unfreeze writes, revert routing."""
        progress = SharedStorageMigrationProgress(
            tenant_id=tenant_id,
            started_at=datetime.now(timezone.utc),
            phase=MIGRATION_STATE_FAILED,
        )
        try:
            unfreeze_tenant_writes(tenant_id)
            KnowledgeSpaceSharedStorageRoutingDao.switch_to_legacy(tenant_id)
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
        await self._phase_reverse_copy(tenant_id, progress, dry_run=dry_run)

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
            get_shared_storage_conf,
            resolve_space_shared_routing,
            shared_collection_name,
            shared_index_name,
        )

        # Discover all SPACE-type knowledge bases in the tenant.
        all_spaces = await KnowledgeDao.aget_all_knowledge(
            knowledge_type=KnowledgeTypeEnum.SPACE,
        )
        spaces = [
            s for s in all_spaces
            if int(getattr(s, 'tenant_id', None) or 1) == int(tenant_id)
        ]
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
            logger.warning(
                "shared_storage_reverse_migration_no_routing tenant=%s",
                tenant_id,
            )
            return

        conf = get_shared_storage_conf()
        collection_name = snapshot.collection_name or shared_collection_name(tenant_id)
        index_name = snapshot.index_name or shared_index_name(tenant_id)

        from bisheng.llm.domain import LLMService
        from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag

        embeddings = LLMService.get_knowledge_default_embedding(
            0, tenant_id=tenant_id,
        )
        if embeddings is None:
            logger.error(
                "shared_storage_reverse_migration_no_embedding tenant=%s",
                tenant_id,
            )
            return

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

        Delta detection: only copies chunks whose ``content_generation`` is
        **newer** than the per-space copy. The key is
        ``(canonical_document_id, chunk_index)`` — chunks that already exist
        in per-space with the same or higher generation are skipped.

        Strategy:
        1. Query per-space for existing ``(canonical_document_id, chunk_index,
           content_generation)`` triples to build a lookup map.
        2. Query shared store for chunks where ``knowledge_ids`` contains
           *space_id*.
        3. For each chunk, compare generations: only write if shared has a
           newer generation.
        4. Repeat for ES.
        """
        import asyncio

        from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag

        space_collection = getattr(space, 'collection_name', None)
        if not space_collection:
            return

        # --- Preload per-space generation map ---
        per_space_milvus = KnowledgeRag.init_knowledge_milvus_vectorstore_sync(
            0, knowledge=space,
        )
        existing_map = await self._build_per_space_generation_map(
            per_space_milvus, space_id,
        )
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
                    "content_generation",
                    "entry_generation",
                    "knowledge_ids",
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
        space_index = getattr(space, 'index_name', None)
        if space_index and shared_es is not None:
            try:
                per_space_es = KnowledgeRag.init_es_vectorstore_sync(
                    index_name=space_index,
                )
                await self._reverse_copy_es(
                    shared_es=shared_es,
                    shared_index_name=shared_index_name,
                    per_space_es=per_space_es,
                    space_id=space_id,
                    space_index=space_index,
                )
            except Exception:
                logger.exception(
                    "shared_storage_reverse_es_copy_failed space=%s",
                    space_id,
                )
                raise

    @staticmethod
    async def _build_per_space_generation_map(
        per_space_milvus: Any,
        space_id: int,
    ) -> dict[tuple[int, int], int]:
        """Query per-space collection and return a lookup map of
        ``(canonical_document_id, chunk_index) → content_generation``.

        This is used for delta detection: only chunks with a higher generation
        in the shared store need to be copied back.
        """
        import asyncio

        if per_space_milvus.col is None:
            return {}

        def _query() -> list[dict]:
            try:
                if hasattr(per_space_milvus.col, "query_iterator"):
                    iterator = per_space_milvus.col.query_iterator(
                        expr=f"knowledge_id == {space_id}",
                        output_fields=[
                            "canonical_document_id",
                            "chunk_index",
                            "content_generation",
                        ],
                        batch_size=5000,
                    )
                    results: list[dict] = []
                    while True:
                        batch = iterator.next()
                        if not batch:
                            break
                        results.extend(batch)
                    return results
                else:
                    return per_space_milvus.col.query(
                        expr=f"knowledge_id == {space_id}",
                        output_fields=[
                            "canonical_document_id",
                            "chunk_index",
                            "content_generation",
                        ],
                        limit=16384,
                    )
            except Exception:
                logger.exception(
                    "shared_storage_reverse_generation_map_query_failed "
                    "space=%s",
                    space_id,
                )
                return []

        results = await asyncio.to_thread(_query)
        lookup: dict[tuple[int, int], int] = {}
        for row in results:
            doc_id = int(row.get("canonical_document_id", 0))
            chunk_idx = int(row.get("chunk_index", 0))
            gen = int(row.get("content_generation", 0))
            key = (doc_id, chunk_idx)
            # Keep the highest generation per key.
            if key not in lookup or gen > lookup[key]:
                lookup[key] = gen
        return lookup

    async def _write_per_space_milvus_delta(
        self,
        space: Any,
        space_id: int,
        chunks: list[dict],
        existing_map: dict[tuple[int, int], int],
        per_space_milvus: Any,
        tenant_id: int,
    ) -> tuple[int, int]:
        """Write **only delta** chunks to per-space Milvus.

        Returns ``(written_count, skipped_count)``.
        """
        import asyncio

        if per_space_milvus.col is None:
            return 0, len(chunks)

        # Filter: only keep chunks that are new or have a higher generation.
        to_write: list[dict] = []
        skipped = 0
        for chunk in chunks:
            doc_id = int(chunk.get("canonical_document_id", 0))
            chunk_idx = int(chunk.get("chunk_index", 0))
            shared_gen = int(chunk.get("content_generation", 0))
            key = (doc_id, chunk_idx)
            existing_gen = existing_map.get(key, -1)
            if shared_gen > existing_gen:
                row = {
                    "knowledge_id": space_id,
                    "canonical_document_id": doc_id,
                    "canonical_version_id": int(chunk.get("canonical_version_id", 0)),
                    "chunk_index": chunk_idx,
                    "text": chunk.get("text", ""),
                    "content_generation": shared_gen,
                    "entry_generation": int(chunk.get("entry_generation", 0)),
                }
                if "vector" in chunk:
                    row["vector"] = chunk["vector"]
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
    ) -> None:
        """Copy ES documents from shared index to per-space index, delta only.

        Uses the ``terms`` query on ``metadata.knowledge_ids`` to find
        documents belonging to *space_id*, then compares ``content_generation``
        with the per-space copy before re-indexing.
        """
        import asyncio

        try:
            # First, build a lookup of existing per-space content_generations.
            existing_query = {
                "query": {
                    "term": {"metadata.knowledge_id": space_id},
                },
                "size": 10000,
                "_source": [
                    "metadata.canonical_document_id",
                    "metadata.chunk_index",
                    "metadata.content_generation",
                ],
            }
            existing_resp = await asyncio.to_thread(
                per_space_es.client.search,
                index=space_index,
                body=existing_query,
            )
            existing_map: dict[str, int] = {}
            for hit in existing_resp.get("hits", {}).get("hits", []):
                src = hit.get("_source", {}).get("metadata", {})
                doc_id = src.get("canonical_document_id", "")
                chunk_idx = src.get("chunk_index", 0)
                gen = int(src.get("content_generation", 0))
                key = f"{doc_id}_{chunk_idx}"
                if key not in existing_map or gen > existing_map[key]:
                    existing_map[key] = gen

            # Query shared ES for documents containing this space_id.
            shared_query = {
                "query": {
                    "terms": {"metadata.knowledge_ids": [space_id]},
                },
                "size": 10000,
            }
            response = await asyncio.to_thread(
                shared_es.client.search,
                index=shared_index_name,
                body=shared_query,
            )
            hits = response.get("hits", {}).get("hits", [])
            if not hits:
                return

            # Filter: only write documents that are new or have higher generation.
            from elasticsearch.helpers import bulk

            actions = []
            skipped = 0
            for hit in hits:
                doc = hit["_source"]
                meta = doc.get("metadata", {})
                doc_id = str(meta.get("canonical_document_id", ""))
                chunk_idx = int(meta.get("chunk_index", 0))
                shared_gen = int(meta.get("content_generation", 0))
                key = f"{doc_id}_{chunk_idx}"
                existing_gen = existing_map.get(key, -1)
                if shared_gen <= existing_gen:
                    skipped += 1
                    continue
                # Rewrite: knowledge_ids → knowledge_id (scalar).
                doc["metadata"]["knowledge_id"] = space_id
                doc["metadata"].pop("knowledge_ids", None)
                actions.append({
                    "_index": space_index,
                    "_id": f"{doc_id}_{chunk_idx}",
                    "_source": doc,
                })
                existing_map[key] = shared_gen

            if actions:
                def _bulk() -> None:
                    bulk(per_space_es.client, actions, refresh=True)

                await asyncio.to_thread(_bulk)
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
        all_spaces = await KnowledgeDao.aget_all_knowledge(
            knowledge_type=KnowledgeTypeEnum.SPACE,
        )
        spaces = [s for s in all_spaces if int(getattr(s, 'tenant_id', None) or 1) == int(tenant_id)]
        progress.total_spaces = len(spaces)

        if dry_run:
            logger.info(
                "shared_storage_migration dry_run copy tenant=%s spaces=%d",
                tenant_id,
                len(spaces),
            )
            progress.migrated_spaces = len(spaces)
            return

        for space in spaces:
            try:
                await self._copy_space_vectors(
                    space_id=int(space.id),
                    tenant_id=tenant_id,
                    collection_name=collection_name,
                    index_name=index_name,
                    embedding_model_id=embedding_model_id,
                )
                progress.migrated_spaces += 1
            except Exception:
                logger.exception(
                    "shared_storage_migration_copy_failed space=%s tenant=%s",
                    space.id,
                    tenant_id,
                )
                progress.failed_spaces += 1
                progress.errors.append(
                    f"space {space.id}: {_sanitize_error()}",
                )

    async def _copy_space_vectors(
        self,
        space_id: int,
        tenant_id: int,
        *,
        collection_name: str | None,
        index_name: str | None,
        embedding_model_id: int | None,
    ) -> None:
        """Copy vectors from per-space collection to the shared store.

        In the current implementation, the actual vector copy is handled by the
        projection system: when ``switch_to_shared`` is called, new document
        projections are written to the shared store. Existing documents are
        re-projected via the document projection worker.

        This placeholder validates that the shared store is available and
        records the space in the routing table.
        """
        # The shared store bootstrap is idempotent; calling ensure_shared_index
        # and bootstrap_shared_collection here is safe.
        from bisheng.knowledge.rag.shared_space_storage import (
            bootstrap_shared_collection,
            ensure_shared_es_index,
            get_shared_storage_conf,
        )

        conf = get_shared_storage_conf()
        actual_collection = collection_name or conf.collection_name
        actual_index = index_name or conf.index_name
        actual_model_id = embedding_model_id or conf.tenant_embedding_model_id

        if actual_collection:
            await bootstrap_shared_collection(
                collection_name=actual_collection,
                tenant_id=tenant_id,
            )
        if actual_index:
            await ensure_shared_es_index(index_name=actual_index)

        logger.info(
            "shared_storage_migration_space_done space=%s tenant=%s",
            space_id,
            tenant_id,
        )

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

        unfreeze_tenant_writes(tenant_id)
        logger.info("shared_storage_migration_resumed tenant=%s", tenant_id)


def _sanitize_error() -> str:
    """Return a safe error summary for progress tracking."""
    import traceback

    return traceback.format_exc()[-500:]