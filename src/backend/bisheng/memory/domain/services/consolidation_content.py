"""Turn a session's new messages into consolidation operations (decision 7, AC-39, AC-42, AC-49).

Reads messages after the watermark up to this run's end id, keeps only user
inputs and system outputs (deep-research task rows, tool rows and workflow
node logs are skipped), asks the memory model for candidates, drops candidates
that fail the content guard, and maps duplicates / contradictions onto existing
items. The operations are applied by ``MemoryService.apply_operations`` in the
consolidator's transaction.
"""

from __future__ import annotations

import json
import re

from loguru import logger
from sqlmodel import select

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.memory.domain.config import aget_memory_config
from bisheng.memory.domain.models.memory_item import ITEM_TYPES
from bisheng.memory.domain.ports import SCENE_LINSIGHT, MemoryContext
from bisheng.memory.domain.repositories import _db
from bisheng.memory.domain.repositories.item_repository import ItemRepository
from bisheng.memory.domain.services.consolidation_prompt import build_prompt
from bisheng.memory.domain.services.guard import validate_item
from bisheng.memory.domain.services.resident import local_today

USER_CATEGORIES = {"question", "input"}
SYSTEM_CATEGORIES = {
    "answer",
    "agent_answer",
    "output_msg",
    "stream_msg",
    "output_with_input_msg",
    "output_with_choose_msg",
}
MAX_MESSAGE_CHARS = 2000
MAX_TOTAL_CHARS = 24000
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def message_text(raw) -> str:
    """Plain text of a stored message (several scenes store JSON envelopes)."""
    if raw is None:
        return ""
    text = str(raw)
    try:
        obj = json.loads(text)
    except (ValueError, TypeError):
        return text
    if isinstance(obj, dict):
        for key in ("msg", "message", "text", "content", "input", "output"):
            value = obj.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return ""
    if isinstance(obj, str):
        return obj
    return text


def parse_candidates(answer: str) -> dict:
    text = _FENCE.sub("", (answer or "").strip())
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("consolidation answer is not JSON")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("consolidation answer is not an object")
    return data


async def load_new_messages(chat_id: str, after_id: int, end_id: int) -> list[tuple[str, str]]:
    from bisheng.database.models.message import ChatMessage

    stmt = (
        select(ChatMessage.category, ChatMessage.message, ChatMessage.is_bot)
        .where(ChatMessage.chat_id == chat_id, ChatMessage.id > after_id, ChatMessage.id <= end_id)
        .order_by(ChatMessage.id.asc())
    )
    async with _db.async_session() as s:
        rows = (await s.exec(stmt)).all()
    out, total = [], 0
    for category, message, _is_bot in rows:
        if category in USER_CATEGORIES:
            role = "用户"
        elif category in SYSTEM_CATEGORIES:
            role = "系统"
        else:
            continue
        text = message_text(message).strip()[:MAX_MESSAGE_CHARS]
        if not text:
            continue
        total += len(text)
        if total > MAX_TOTAL_CHARS:
            break
        out.append((role, text))
    return out


def map_candidates(data: dict, existing_ids: set[str]) -> list[dict]:
    ops: list[dict] = []
    for cand in data.get("candidates") or []:
        if not isinstance(cand, dict):
            continue
        item_type = cand.get("type") or "fact"
        try:
            content = validate_item(cand.get("content"), item_type)
        except BaseErrorCode as exc:
            logger.info("memory consolidation candidate rejected: {}", exc.message)
            continue
        if cand.get("duplicate_of") in existing_ids:
            continue
        op = {
            "content": content,
            "type": item_type if item_type in ITEM_TYPES else "fact",
            "event_time": cand.get("event_time"),
            "pinned": bool(cand.get("pinned")),
        }
        target = cand.get("contradicts")
        if target in existing_ids:
            ops.append({"op": "supersede", "target_id": target, **op})
        else:
            ops.append({"op": "add", **op})
    for change in data.get("pin_changes") or []:
        if isinstance(change, dict) and change.get("id") in existing_ids:
            ops.append({"op": "pin", "target_id": change["id"], "pinned": bool(change.get("pinned"))})
    return ops


class ConsolidationContent:
    """Callable used as ``Consolidator.content_fn``."""

    def __init__(self, llm):
        self.llm = llm

    async def __call__(self, ctx: MemoryContext, cursor, end_id: int) -> list[dict]:
        messages = await load_new_messages(cursor.chat_id, cursor.watermark_message_id, end_id)
        if not messages:
            return []
        return await self.from_messages(ctx, messages)

    async def from_messages(self, ctx: MemoryContext, messages: list[tuple[str, str]]) -> list[dict]:
        config = await aget_memory_config()
        async with _db.async_session() as s:
            existing = await ItemRepository.list_active(s, ctx)
        existing_view = [{"id": i.id, "type": i.type, "content": i.content, "pinned": i.pinned} for i in existing]
        today = local_today(ctx.timezone, config.default_timezone).strftime("%Y-%m-%d")
        mode = "linsight" if ctx.scene == SCENE_LINSIGHT else "chat"
        prompt = build_prompt(today, messages, existing_view, config.resident_max_items, mode=mode)
        answer = await self.llm.consolidate(ctx, prompt)
        return map_candidates(parse_candidates(answer), {i["id"] for i in existing_view})
