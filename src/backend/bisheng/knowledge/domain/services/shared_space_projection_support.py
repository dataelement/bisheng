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
    return bool(enabled)


async def resolve_shared_space_storage_enabled() -> bool:
    """Defensively resolve the shared-storage switch; missing/off => False.

    F1 owns the ``knowledge_space_shared_storage`` config block; until it lands
    (or on any config/DB error) this returns False so every caller keeps the
    legacy behaviour. Never imports F1 symbols.
    """
    try:
        from bisheng.common.services.config_service import settings as bisheng_settings

        conf = await bisheng_settings.async_get_knowledge()
    except Exception:
        return False
    try:
        return shared_space_block_enabled(
            getattr(conf, "knowledge_space_shared_storage", None)
        )
    except Exception:
        logger.debug(
            "shared-space storage config present but unreadable; treating as disabled",
            exc_info=True,
        )
        return False


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
