"""F132 long-term memory for assistants (design decisions 10, 11, 15; R1, R2, R6).

``AssistantAgent`` builds its agent once per connection, so memory is applied per
turn: ``begin_turn`` re-reads ``assistant.memory_enabled`` from the database,
resolves the session registration, loads the resident block and builds the two
memory tools; ``finish_turn`` sends the stream signal; ``end_turn`` binds the
turn record to the answer and marks the session for consolidation.

Memory never breaks a turn: every failure here is logged (and counted where it
is an inject failure, AC-61) and the turn continues without memory.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from loguru import logger

from bisheng.memory.domain.ports import SCENE_ASSISTANT, MemoryContext
from bisheng.memory.domain.services import factory
from bisheng.memory.domain.services import metrics as m
from bisheng.memory.domain.services.activity import MemoryActivity
from bisheng.memory.domain.services.app_switch import assistant_memory_enabled
from bisheng.memory.domain.services.gate import MemoryGate
from bisheng.memory.domain.services.redaction import (
    is_memory_tool,
    redact_text,
    redact_tool_event,
    replay_placeholder,
    split_reserved_tools,
)
from bisheng.memory.domain.services.resident import SCENE_CLASS_CHAT
from bisheng.memory.domain.services.tools import build_memory_tools
from bisheng.memory.domain.services.turn_record import TurnRecordService

RESIDENT_MESSAGE_ID = "f132-memory-resident"


@dataclass
class AssistantMemoryTurn:
    """State of one assistant turn; ``ctx`` is None when memory is off for it."""

    ctx: MemoryContext | None = None
    resident_text: str = ""
    tools: list = field(default_factory=list)
    signalled: bool = False

    @property
    def enabled(self) -> bool:
        return self.ctx is not None

    def flags(self) -> dict:
        ctx = self.ctx
        return {
            "turn_id": ctx.turn_id if ctx else None,
            "has_write": bool(ctx and ctx.extra.get("memory_written")),
            "has_attribution": bool(ctx and (self.resident_text or ctx.extra.get("memory_retrieved"))),
        }


async def send_signal(callbacks, payload: dict) -> None:
    """Send the ``memory`` WebSocket message through the assistant's callback handler."""
    for handler in callbacks or []:
        sender = getattr(handler, "send_memory_signal", None)
        if sender is None:
            continue
        try:
            await sender(payload)
        except Exception:
            # The signal is a UI hint; the turn and its records are unaffected.
            logger.exception("memory: sending assistant memory signal failed")
        return


async def begin_turn(
    assistant, chat_id: str | None, callbacks=None, actor_user_id: int | None = None
) -> AssistantMemoryTurn:
    """Re-read the switch, resolve enablement, load resident memory and build tools."""
    turn = AssistantMemoryTurn()
    if not chat_id:
        return turn
    try:
        enabled, name = await assistant_memory_enabled(getattr(assistant, "id", None))
        if not enabled:
            return turn
        turn.ctx = await MemoryGate.resolve(
            chat_id,
            SCENE_ASSISTANT,
            app_enabled=enabled,
            app_id=getattr(assistant, "id", None),
            app_name=name or getattr(assistant, "name", None),
            actor_user_id=actor_user_id,
        )
    except Exception:
        logger.exception("memory: assistant enablement check failed; this turn runs without memory")
        turn.ctx = None
    if turn.ctx is None:
        return turn
    ctx = turn.ctx

    resident_rev, resident_day = None, None
    try:
        block = await factory.get_resident_service().resident(ctx, SCENE_CLASS_CHAT)
        if block.text:
            turn.resident_text = block.text
            resident_rev, resident_day = block.rev, block.day
    except Exception:
        logger.exception("memory: resident memory injection failed for assistant turn")
        await _count(ctx, m.INJECT_FAILED)

    async def _on_write(_result):
        await send_signal(callbacks, turn.flags())

    try:
        turn.tools = build_memory_tools(ctx, on_write=_on_write)
    except Exception:
        logger.exception("memory: building memory tools failed")
        turn.tools = []

    try:
        # One summary row per enabled turn; resident_rev stays None when nothing was
        # injected so the flags do not claim an attribution (decision 15).
        await TurnRecordService.add_summary(ctx, resident_rev, resident_day, SCENE_CLASS_CHAT)
    except Exception:
        logger.exception("memory: writing the turn summary failed")
    return turn


async def _count(ctx: MemoryContext, metric: str) -> None:
    try:
        await factory.get_metrics().incr(ctx, metric)
    except Exception:
        logger.exception("memory: metric increment failed")


def compose_tools(author_tools: list, turn: AssistantMemoryTurn) -> list:
    """Author tools plus the memory tools; reserved names lose to the built-ins."""
    if not turn.enabled:
        return list(author_tools)
    kept, _dropped = split_reserved_tools(author_tools)
    return kept + list(turn.tools)


def prepare_inputs(inputs: list, turn: AssistantMemoryTurn) -> list:
    """Copy the trimmed inputs, neutralise replayed memory results, insert the resident block.

    The copy keeps the caller's list untouched (R6); the resident message goes right
    before the last message because ReAct reads ``inputs[-1]`` as the question.
    """
    prepared = [_replay(one) for one in inputs]
    changed = any(a is not b for a, b in zip(prepared, inputs))
    if turn.resident_text and prepared:
        prepared.insert(len(prepared) - 1, SystemMessage(content=turn.resident_text, id=RESIDENT_MESSAGE_ID))
        changed = True
    # Nothing to change: hand back the very same list so memory-off turns behave
    # exactly as before (the client's result slice depends on list aliasing, V5).
    return prepared if changed else inputs


def _is_memory_result(message) -> bool:
    if not isinstance(message, ToolMessage):
        return False
    if is_memory_tool(getattr(message, "name", None)):
        return True
    content = message.content
    if isinstance(content, str) and '"redacted"' in content:
        try:
            obj = json.loads(content)
        except (ValueError, TypeError):
            return False
        return isinstance(obj, dict) and obj.get("redacted") is True
    return False


def _replay(message):
    if _is_memory_result(message):
        return message.model_copy(update={"content": replay_placeholder()})
    return message


def finalize_result(result: list) -> list:
    """Drop the injected resident message and redact memory tool calls and results (path one)."""
    memory_call_ids: dict[str, str] = {}
    out = []
    for one in result:
        if getattr(one, "id", None) == RESIDENT_MESSAGE_ID:
            continue
        if isinstance(one, AIMessage) and one.tool_calls:
            one = _redact_ai_message(one, memory_call_ids)
        elif isinstance(one, ToolMessage):
            name = getattr(one, "name", None) or memory_call_ids.get(one.tool_call_id)
            if is_memory_tool(name):
                one = one.model_copy(update={"content": redact_text(name, one.content), "artifact": None})
        elif hasattr(one, "tool") and hasattr(one, "tool_input") and is_memory_tool(getattr(one, "tool", None)):
            # ReAct AgentAction objects: never persisted, but carry raw arguments.
            update = {"tool_input": redact_tool_event(one.tool, one.tool_input), "log": ""}
            one = one.model_copy(update=update) if hasattr(one, "model_copy") else one.copy(update=update)
        out.append(one)
    return out


def _redact_ai_message(message: AIMessage, memory_call_ids: dict[str, str]) -> BaseMessage:
    if not any(is_memory_tool(call.get("name")) for call in message.tool_calls):
        return message
    tool_calls = []
    for call in message.tool_calls:
        if is_memory_tool(call.get("name")):
            memory_call_ids[call.get("id")] = call["name"]
            call = {**call, "args": redact_tool_event(call["name"], call.get("args") or {})}
        tool_calls.append(call)
    additional = dict(message.additional_kwargs or {})
    if additional.get("tool_calls"):
        raw_calls = []
        for raw in additional["tool_calls"]:
            fn = dict(raw.get("function") or {})
            if is_memory_tool(fn.get("name")):
                fn["arguments"] = json.dumps(redact_tool_event(fn["name"], fn.get("arguments")), ensure_ascii=False)
                raw = {**raw, "function": fn}
            raw_calls.append(raw)
        additional["tool_calls"] = raw_calls
    return message.model_copy(
        update={"tool_calls": tool_calls, "additional_kwargs": additional, "invalid_tool_calls": []}
    )


async def finish_turn(turn: AssistantMemoryTurn | None, callbacks) -> None:
    """Send the ``memory`` signal when the turn wrote or used memory (AC-21, AC-87)."""
    if turn is None or not turn.enabled:
        return
    flags = turn.flags()
    if flags["has_write"] or flags["has_attribution"]:
        await send_signal(callbacks, flags)


async def end_turn(chat_id: str | None, turn: AssistantMemoryTurn | None, message_id: Any) -> None:
    """After the answer row is persisted (or the turn failed): bind and mark for consolidation."""
    if not chat_id or turn is None:
        return
    try:
        if turn.ctx is not None and message_id:
            await TurnRecordService.bind_turn(turn.ctx, int(message_id))
        await MemoryActivity.end_turn(chat_id, int(message_id) if message_id else None, turn.enabled)
    except Exception:
        logger.exception("memory: ending the assistant turn failed")
