"""Read models returned by the memory management API."""

from __future__ import annotations

from bisheng.memory.domain.ports import MemoryContext
from bisheng.memory.domain.services.search import source_of
from bisheng.memory.domain.services.turn_record import TurnRecordService


def item_view(item) -> dict:
    return {
        "id": item.id,
        "content": item.content,
        "type": item.type,
        "status": item.status,
        "recorded_at": item.recorded_at.strftime("%Y-%m-%d %H:%M") if item.recorded_at else None,
        "event_time": item.event_time.strftime("%Y-%m-%d") if item.event_time else None,
        "source": source_of(item),
        "pinned": bool(item.pinned),
        "has_detail": bool(item.detail_object_key),
    }


async def turn_view(ctx: MemoryContext, service, *, turn_id=None, message_id=None) -> dict:
    """Writes (with item text, any status), retrieved items, resident items of one turn."""
    records = await TurnRecordService.get_for_owner(ctx, turn_id=turn_id, message_id=message_id)
    out = {"turn_id": records["turn_id"], "writes": [], "retrieved": [], "resident": []}
    write_ids = [i for w in records["writes"] for i in (w["item_id"], w["related_item_id"]) if i]
    all_items = {i.id: i for i in await service.get_items(ctx, write_ids, active_only=False)}
    for w in records["writes"]:
        out["writes"].append(
            {
                **w,
                "item": item_view(all_items[w["item_id"]]) if w["item_id"] in all_items else None,
                "related_item": item_view(all_items[w["related_item_id"]])
                if w["related_item_id"] in all_items
                else None,
            }
        )
    retrieved = {i.id: i for i in await service.get_items(ctx, records["retrieved_item_ids"])}
    out["retrieved"] = [item_view(retrieved[i]) for i in records["retrieved_item_ids"] if i in retrieved]
    summary = records["summary"]
    if summary and summary["resident_rev"] is not None:
        ids = await TurnRecordService.get_snapshot(
            ctx, summary["resident_rev"], summary["resident_day"], summary["scene_class"] or "chat"
        )
        resident = {i.id: i for i in await service.get_items(ctx, ids)}
        out["resident"] = [item_view(resident[i]) for i in ids if i in resident]
    return out
