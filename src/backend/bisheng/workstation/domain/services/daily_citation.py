"""Daily chat citation glue for the short-handle contract (F072).

Kept out of ``chat_service.py`` so the turn loop only gains call sites:

- tool output: show ``<ref>S3</ref>`` / ``"ref": "S7"`` instead of registry
  keys (:func:`handles_for_chunks`, :func:`handles_for_web_results`);
- completion: bind exactly the sources the answer cites, including sources
  retrieved in earlier turns (:func:`select_cited_items`,
  :func:`select_cited_items_sync`);
- one audit log line per turn (:func:`log_citation_audit`).

Nothing here may break a turn: every failure degrades to "no citation this
turn" and a log line (spec AC-17). There is no fallback to the old
verbatim-id contract (design §3 decision 6).
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from bisheng.citation.domain.schemas.citation_schema import CitationRegistryItemSchema
from bisheng.citation.domain.services.citation_handle_service import (
    assign_handles,
    drop_chunk_ids,
    drop_web_citation_keys,
    rewrite_web_results_with_handles,
    swap_chunk_id_for_handle,
)
from bisheng.citation.domain.services.citation_prompt_helper import (
    extract_citation_ids_from_text,
    filter_registry_items_by_text,
)
from bisheng.citation.domain.services.citation_runtime_cache_service import CitationRuntimeCacheService
from bisheng.citation.domain.services.daily_citation_handles import StreamStats
from bisheng.citation.domain.services.daily_citation_scope import DailyCitationScope

_runtime_cache = CitationRuntimeCacheService()


# --------------------------------------------------------------------------
# tool output
# --------------------------------------------------------------------------
async def handles_for_chunks(
    scope: DailyCitationScope | None,
    items: list[CitationRegistryItemSchema],
    chunks: list[str],
) -> list[str]:
    """Swap each chunk's registry key for its handle; drop keys left without one."""
    if scope is None:
        return chunks
    scope.record_seen(items)
    handles = await assign_handles(scope, items) if items else {}
    if items and not handles:
        logger.error(f"[daily-citation] handle allocation failed chat={scope.session_id}; results carry no source id")
    return [drop_chunk_ids(swap_chunk_id_for_handle(chunk, handles)) for chunk in chunks]


async def handles_for_web_results(
    scope: DailyCitationScope | None,
    items: list[CitationRegistryItemSchema],
    annotated: Any,
) -> Any:
    """Show ``"ref": "S7"`` on web results; drop keys left without a handle."""
    if scope is None:
        return annotated
    scope.record_seen(items)
    handles = await assign_handles(scope, items) if items else {}
    if items and not handles:
        logger.error(f"[daily-citation] handle allocation failed chat={scope.session_id}; results carry no source id")
    return drop_web_citation_keys(rewrite_web_results_with_handles(annotated, handles))


def strip_ids_for_sync_path(scope: DailyCitationScope | None, chunks: list[str]) -> list[str]:
    """Sync tool calls cannot await the allocator: show no source id at all."""
    if scope is None:
        return chunks
    return [drop_chunk_ids(chunk) for chunk in chunks]


# --------------------------------------------------------------------------
# completion
# --------------------------------------------------------------------------
def _missing_ids(collected: list[CitationRegistryItemSchema], text: str) -> list[str]:
    known = {item.citationId for item in collected if item.citationId}
    return sorted(cid for cid in extract_citation_ids_from_text(text) if cid not in known)


def _merge(collected: list[CitationRegistryItemSchema], extra: list[CitationRegistryItemSchema], text: str):
    # Strict: only what the answer cites; nothing when it cites nothing (AC-14).
    return filter_registry_items_by_text([*collected, *extra], text)


async def select_cited_items(
    collected: list[CitationRegistryItemSchema],
    text: str,
) -> list[CitationRegistryItemSchema]:
    """Sources to bind to this answer: cited ones only, earlier turns included (AC-12)."""
    extra: list[CitationRegistryItemSchema] = []
    missing = _missing_ids(collected, text)
    if missing:
        try:
            extra = await _runtime_cache.get_citations_by_ids(missing)
        except Exception:
            logger.opt(exception=True).warning("[daily-citation] cross-turn source lookup failed")
    return _merge(collected, extra, text)


def select_cited_items_sync(
    collected: list[CitationRegistryItemSchema],
    text: str,
) -> list[CitationRegistryItemSchema]:
    """Same as :func:`select_cited_items` for the interruption path (no await)."""
    extra: list[CitationRegistryItemSchema] = []
    missing = _missing_ids(collected, text)
    if missing:
        try:
            extra = _runtime_cache.get_citations_by_ids_sync(missing)
        except Exception:
            logger.opt(exception=True).warning("[daily-citation] cross-turn source lookup failed")
    return _merge(collected, extra, text)


def log_citation_audit(
    *,
    chat_id: str,
    model: Any,
    scope: DailyCitationScope | None,
    stats: StreamStats,
    cited: list[CitationRegistryItemSchema],
) -> None:
    """One line per turn (AC-13); WARNING when sources were seen but none cited."""
    seen = len(scope.seen_keys) if scope is not None else 0
    line = (
        f"[daily-citation-audit] chat={chat_id} model={model} sources_seen={seen} cited={len(cited)} "
        f"unknown_handles={len(stats.unknown)} legacy_markers={stats.legacy_markers}"
    )
    if seen and not cited:
        logger.warning(line)
    else:
        logger.info(line)
