"""Shared helpers for the F2 content/membership dual projection (refactor 3.7).

This module owns the pieces of the shared-storage projection that must stay
free of infrastructure imports:

- defensive resolution of the ``knowledge_space_shared_storage`` config block
  (owned by F1; may not exist yet, missing/off => legacy behaviour, spec 6.2);
- pure re-aggregation of ``knowledge_ids`` from SQL active entries (spec 3.4:
  blind add/remove on the previous array is forbidden);
- the chunk-loader callable type used to build ``ContentUpsertRequest`` payloads.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence

from bisheng.knowledge.domain.contracts.shared_space_storage import (
    SharedContentChunk,
    validate_knowledge_ids,
)
from bisheng.knowledge.domain.models.knowledge_file import (
    KnowledgeFile,
    KnowledgeFileEntryStatus,
    KnowledgeFileEntryType,
)

logger = logging.getLogger(__name__)

#: Loads the chunk payload of the primary physical content file for a content
#: projection write. Injected by callers; tests use fakes.
SharedContentChunkLoader = Callable[
    [KnowledgeFile],
    Awaitable[Sequence[SharedContentChunk]],
]

#: Entry types whose active rows contribute a space to ``knowledge_ids``.
MEMBERSHIP_ENTRY_TYPES = frozenset(
    {
        KnowledgeFileEntryType.MANAGER.value,
        KnowledgeFileEntryType.PUBLISH.value,
        KnowledgeFileEntryType.SHARE.value,
    }
)


def shared_space_block_enabled(block: object | None) -> bool:
    """Interpret one ``knowledge_space_shared_storage`` config block value.

    Accepts a bool, an object with ``enabled``, or a mapping/dict with an
    ``enabled`` key. Anything else (including None) means disabled.
    """
    if block is None:
        return False
    if isinstance(block, bool):
        return block
    enabled = getattr(block, "enabled", None)
    if enabled is None and isinstance(block, dict):
        enabled = block.get("enabled")
    return enabled if isinstance(enabled, bool) else False


async def resolve_shared_space_storage_enabled() -> bool:
    """Defensively resolve the shared-storage switch; missing/off => False.

    F1 owns the ``knowledge_space_shared_storage`` config block; until it lands
    (or on any config/DB error) this returns False so every caller keeps the
    legacy behaviour. Never imports F1 symbols.
    """
    try:
        from bisheng.common.services.config_service import settings as bisheng_settings
    except Exception:
        return False
    try:
        return shared_space_block_enabled(
            getattr(bisheng_settings, "knowledge_space_shared_storage", None)
        )
    except Exception:
        logger.debug(
            "shared-space storage config present but unreadable; treating as disabled",
            exc_info=True,
        )
        return False


async def load_shared_content_chunks_from_legacy(
    content_file: KnowledgeFile,
) -> Sequence[SharedContentChunk]:
    """Load the physical file's existing chunks from its legacy collection.

    Projection workers already have durable vectors in the per-space store;
    shared projection must copy those vectors instead of silently producing an
    empty content projection or embedding them again.
    """
    from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
    from bisheng.knowledge.domain.models.knowledge import KnowledgeDao

    source_space_ids = [int(content_file.knowledge_id)]
    if (
        content_file.original_knowledge_id is not None
        and int(content_file.original_knowledge_id) not in source_space_ids
    ):
        source_space_ids.append(int(content_file.original_knowledge_id))
    source_spaces = []
    for space_id in source_space_ids:
        knowledge = await KnowledgeDao.aquery_by_id(space_id)
        if knowledge is not None:
            source_spaces.append(knowledge)
    if not source_spaces:
        raise RuntimeError(
            f"knowledge spaces {source_space_ids} not found for content file "
            f"{content_file.id}"
        )

    def _load() -> list[SharedContentChunk]:
        for knowledge in source_spaces:
            vector_store = KnowledgeRag.init_knowledge_milvus_vectorstore_sync(
                0, knowledge=knowledge
            )
            collection = vector_store.col
            output_fields = [field.name for field in collection.schema.fields]
            if "document_id" not in output_fields:
                logger.debug(
                    "skip non-legacy collection while loading shared projection "
                    "chunks file_id=%s knowledge_id=%s",
                    content_file.id,
                    knowledge.id,
                )
                continue
            expr = f"document_id == {int(content_file.id)}"
            rows: list[dict] = []
            if hasattr(collection, "query_iterator"):
                iterator = collection.query_iterator(
                    expr=expr,
                    output_fields=output_fields,
                    batch_size=1000,
                )
                try:
                    while batch := iterator.next():
                        rows.extend(batch)
                finally:
                    iterator.close()
            else:
                rows.extend(
                    collection.query(
                        expr=expr,
                        output_fields=output_fields,
                        limit=16384,
                    )
                )

            if not rows:
                continue

            desired_generation = int(
                content_file.desired_content_generation or 0
            )

            def row_generation(row: dict) -> int | None:
                user_metadata = row.get("user_metadata")
                if not isinstance(user_metadata, dict):
                    return None
                value = user_metadata.get("content_generation")
                try:
                    return int(value) if value is not None else None
                except (TypeError, ValueError):
                    return None

            generations = {
                generation
                for row in rows
                if (generation := row_generation(row)) is not None
            }
            selected_generation = (
                desired_generation
                if desired_generation in generations
                else max(generations, default=None)
            )
            if selected_generation is not None:
                rows = [
                    row
                    for row in rows
                    if row_generation(row) == selected_generation
                ]

            chunks_by_index: dict[int, SharedContentChunk] = {}
            corrupted = False
            for offset, row in enumerate(rows):
                metadata = {
                    key: value
                    for key, value in row.items()
                    if key not in {"pk", "text", "vector"}
                }
                raw_chunk_index = row.get("chunk_index")
                chunk_index = (
                    offset
                    if raw_chunk_index is None
                    else int(raw_chunk_index)
                )
                chunk = SharedContentChunk(
                    chunk_index=chunk_index,
                    text=str(row.get("text", "")),
                    vector=row.get("vector"),
                    metadata=metadata,
                )
                existing = chunks_by_index.get(chunk_index)
                if existing is None:
                    chunks_by_index[chunk_index] = chunk
                    continue
                existing_vector = (
                    tuple(existing.vector)
                    if existing.vector is not None
                    else None
                )
                chunk_vector = (
                    tuple(chunk.vector) if chunk.vector is not None else None
                )
                existing_sparse = tuple(
                    sorted((existing.sparse_vector or {}).items())
                )
                chunk_sparse = tuple(sorted((chunk.sparse_vector or {}).items()))
                if (
                    existing.text != chunk.text
                    or existing_vector != chunk_vector
                    or existing_sparse != chunk_sparse
                ):
                    corrupted = True
                    break
            indexes = sorted(chunks_by_index)
            if corrupted or indexes != list(range(len(indexes))):
                logger.warning(
                    "skip corrupted legacy chunk source file_id=%s knowledge_id=%s "
                    "generation=%s rows=%s unique_indexes=%s",
                    content_file.id,
                    knowledge.id,
                    selected_generation,
                    len(rows),
                    len(indexes),
                )
                continue
            return [chunks_by_index[index] for index in indexes]
        return []

    return await asyncio.to_thread(_load)


def aggregate_active_knowledge_ids(
    entries: Sequence[KnowledgeFile],
) -> tuple[int, ...]:
    """Re-aggregate ``knowledge_ids`` from the document's active entries.

    Spec 3.4: every membership update must re-derive the whole array from the
    SQL active manager/publish/share entries (ascending, deduplicated). The
    empty tuple is returned when no active entry remains - callers must then
    short-circuit to the content tombstone flow, never write an empty array.
    """
    space_ids = {
        int(entry.knowledge_id)
        for entry in entries
        if entry.entry_type in MEMBERSHIP_ENTRY_TYPES
        and entry.entry_status == KnowledgeFileEntryStatus.ACTIVE.value
    }
    return tuple(sorted(space_ids))


def normalise_membership_ids(knowledge_ids: Sequence[int]) -> tuple[int, ...]:
    """Contract-validated membership tuple for writer requests."""
    return validate_knowledge_ids(knowledge_ids)
