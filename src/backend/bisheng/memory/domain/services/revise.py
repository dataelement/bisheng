"""Revise one memory item from a plain-language instruction (AC-107).

The user tells the AI how to change an item ("the trip moved to January"); the
memory model rewrites the summary, detail, type and event date, and the result
goes through the same path as a hand edit (validation, supersede, audit as
``revise``). The previous version is returned so the page can undo the change
by editing it back. Nothing is written when the model fails or its answer does
not pass validation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from loguru import logger

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.memory import MemoryItemNotFoundError, MemoryReviseFailedError
from bisheng.memory.domain.ports import MemoryContext
from bisheng.memory.domain.services.consolidation_content import parse_candidates
from bisheng.memory.domain.services.resident import local_today

REVISE_TIMEOUT_SECONDS = 60
ITEM_TYPES = ("fact", "preference", "experience")

PROMPT = """你负责按用户的要求修改他的一条长期记忆。用户时区下今天是 {today}。

当前记忆：
{current}

用户的要求：{instruction}

规则：
- summary 是一句话结论，200 字以内；detail 是需要连贯说明的完整内容，可以为空字符串。
- 只按要求改动相关部分，其余内容保持原样。
- 时间一律写成具体日期（YYYY-MM-DD），不要写"明天""下个月"这类相对时间。
- 不要写入密码、密钥、证件号、银行卡号。
- type 只能是 fact（事实）、preference（偏好）、experience（经验）之一。
- event_time 是事件发生的具体日期（YYYY-MM-DD），没有就填 null。
- 要求与这条记忆无关或无法照做时，原样返回当前记忆。

只输出一个 JSON 对象，不要输出其它文字：
{{"summary": "...", "detail": "...", "type": "fact", "event_time": null}}"""


@dataclass
class Revision:
    item_id: str
    previous: dict
    #: False when the model kept everything as it was (nothing is written then).
    changed: bool = True


def _current_view(item, detail: str | None) -> dict:
    return {
        "summary": item.content,
        "detail": detail or "",
        "type": item.type,
        "event_time": item.event_time.strftime("%Y-%m-%d") if item.event_time else None,
    }


async def revise_item(ctx: MemoryContext, item_id: str, instruction: str, service, llm) -> Revision:
    instruction = (instruction or "").strip()
    items = await service.get_items(ctx, [item_id])
    if not items:
        raise MemoryItemNotFoundError()
    item = items[0]
    previous = _current_view(item, await service.get_detail(ctx, item_id))

    prompt = PROMPT.format(
        today=local_today(ctx.timezone).strftime("%Y-%m-%d"),
        current=json.dumps(previous, ensure_ascii=False, indent=2),
        instruction=instruction,
    )
    try:
        answer = await llm.consolidate(ctx, prompt, timeout=REVISE_TIMEOUT_SECONDS)
        data = parse_candidates(answer)
    except BaseErrorCode:
        raise  # e.g. no memory model configured (12112)
    except Exception as exc:
        logger.warning("memory revise: model call or answer failed item={} err={!r}", item_id, exc)
        raise MemoryReviseFailedError() from exc

    summary = data.get("summary")
    detail = data.get("detail")
    item_type = data.get("type")
    event_time = data.get("event_time") or None
    if not isinstance(summary, str) or not isinstance(detail, (str, type(None))) or item_type not in ITEM_TYPES:
        logger.warning("memory revise: answer has the wrong shape item={}", item_id)
        raise MemoryReviseFailedError()
    proposed = {
        "summary": summary.strip(),
        "detail": (detail or "").strip(),
        "type": item_type,
        "event_time": event_time,
    }
    if proposed == {**previous, "detail": previous["detail"].strip()}:
        return Revision(item_id=item_id, previous=previous, changed=False)
    try:
        result = await service.edit(ctx, item_id, summary, item_type, event_time, detail=detail or "", verb="revise")
    except BaseErrorCode:
        raise  # validation (length, sensitive content, relative time) keeps its own message
    except ValueError as exc:  # e.g. an unparseable event_time
        logger.warning("memory revise: invalid field item={} err={!r}", item_id, exc)
        raise MemoryReviseFailedError() from exc
    return Revision(item_id=result.item_id, previous=previous)
