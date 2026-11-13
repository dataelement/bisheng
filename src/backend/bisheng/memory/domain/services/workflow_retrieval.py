"""Memory retrieval for the workflow ``memory_retriever`` node (design §4.2, AC-81–AC-84).

Output items are ``{text, metadata{type, recorded_at, event_time, source}}``.
``text`` always starts with the background prefix and the recorded date, so the
note travels with the content however a downstream node references it (AC-57).
Items that have a detail object carry the full detail text (AC-82). A search
failure propagates as ``MemorySearchUnavailableError`` (AC-84); this module never
writes turn records (the workflow scene has no attribution, decision 15).
"""

from __future__ import annotations

from loguru import logger

from bisheng.memory.domain.ports import MemoryContext, detail_object_key
from bisheng.memory.domain.services import metrics as m
from bisheng.memory.domain.services.search import SearchHit, SearchService

BACKGROUND_PREFIX = "［背景信息，记录于 {date}］"


def to_node_item(hit: SearchHit) -> dict:
    data = hit.to_dict()
    body = hit.detail or hit.content
    return {
        "text": BACKGROUND_PREFIX.format(date=data["recorded_at"]) + body,
        "metadata": {
            "type": data["type"],
            "recorded_at": data["recorded_at"],
            "event_time": data["event_time"],
            "source": data["source"],
        },
    }


async def _fill_details(search: SearchService, ctx: MemoryContext, hits: list[SearchHit]) -> None:
    """Read the detail text of every hit that has one.

    ``SearchService.search`` only reads details for ids known before the call;
    the node wants all of them, so they are read here with the same key scheme
    the detail store writes. A failed read keeps the short content.
    """
    read = []
    for hit in hits:
        if not hit.has_detail or hit.detail is not None:
            continue
        try:
            hit.detail = await search.details.get(detail_object_key(ctx.tenant_id, ctx.user_id, hit.item_id))
            read.append(hit.item_id)
        except Exception as exc:
            logger.warning("memory detail read failed item={} err={!r}", hit.item_id, exc)
            await search.metrics.incr(ctx, m.DETAIL_READ_FAILED)
    if read:
        await search.metrics.mark_detail_read(ctx, read)


async def retrieve_for_workflow(
    ctx: MemoryContext, query: str, limit: int, search: SearchService | None = None
) -> list[dict]:
    if search is None:
        from bisheng.memory.domain.services.factory import get_search_service

        search = get_search_service()
    hits = await search.search(ctx, query, limit=limit)
    await _fill_details(search, ctx, hits)
    return [to_node_item(h) for h in hits]
