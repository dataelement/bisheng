"""Invalid tool-call repair middleware for Linsight (``after_model``).

Incident (2026-08-27, 114, session ea5d2cee… / version 6049532c…): the model
decided — correctly — to ``ask_user`` for a clarification, but the ``arguments``
string it emitted was not valid JSON (an unescaped ``"`` inside the ``question``
text: ``"question": "您说的"按照各市要求"具体是指什么？"``). langchain parks such a
call in ``AIMessage.invalid_tool_calls``; the agent loop's model→tools edge only
looks at ``tool_calls`` (``factory._make_model_to_tools_edge``: ``len(tool_calls)
== 0`` → END), so the graph ended on an empty-content AIMessage, no ToolMessage
ever reached the model, and the task closed as ``Task produced no result``
(11090). The three ``ask_user`` self-heal layers in ``agent_factory``
(``_coerce_questions`` / options salvage / empty-questions nudge) never ran —
they live INSIDE the tool body, one layer below the JSON parse that failed.

This middleware sits right after the model node and handles the AIMessage
before the routing edge sees it:

1. **Repair** — ``json_repair`` recovers the intended dict for every invalid
   call (on the live payload it restores the question text byte-for-byte). A
   repaired call is written back as a real ``tool_calls`` entry on a copy of the
   AIMessage with the SAME id, so the ``messages`` reducer replaces the message
   in place, the edge routes it to the tools node, and the stream mapper — which
   already emitted the ``start`` frame from the streamed chunks — closes it with
   the normal end frame (langgraph dedupes node-output messages by id, so no
   duplicate start frame is emitted).
2. **Nudge** — a call that cannot be repaired (or whose repaired keys are not a
   subset of the tool's schema, i.e. the repair produced debris) gets an error
   ``ToolMessage`` explaining the JSON error and how to fix it. If the turn has no
   valid call left at all, the middleware jumps straight back to the model so it
   can re-issue the call — ONCE per user turn (counted via the marker in the
   ToolMessage), mirroring the empty-questions nudge's no-infinite-retry rule.
   On the second miss the ToolMessage is still appended (keeps the transcript
   consistent for the next request: langchain_openai serialises
   ``invalid_tool_calls`` into the outgoing ``tool_calls``, so an unanswered one
   would 400 on strict OpenAI-compatible endpoints) but the loop ends as before.

Runs FIRST among the ``after_model`` hooks (they execute in reverse middleware
order and this one is appended last), so the tool-loop breaker and deepagents'
TodoList hook see the repaired call, not the invalid one.

One instance per graph (main + researcher subagent) — the subagent's graph is
outside the main-graph middleware, exactly like the tool-loop breaker.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from typing import Any

from json_repair import json_repair
from langchain.agents.middleware.types import AgentMiddleware, hook_config
from langchain_core.messages import AIMessage, ToolMessage
from loguru import logger

# Substring of the corrective ToolMessage so a later pass can count "already
# nudged this turn" from the message history alone (no per-instance state — the
# agent is rebuilt on resume and a middleware attribute would not survive).
INVALID_ARGS_MARKER = "参数不是合法的 JSON"

_INVALID_ARGS_HINT = (
    "⚠️ 你上一次对 {name} 的调用没有执行：{marker}（{error}）。"
    "最常见的原因是字符串值内部出现了未转义的英文双引号。"
    "请只重新调用一次 {name}，并保证参数是合法 JSON："
    '字符串内需要引号时改用中文引号「」/“”，或写成 \\" 转义；'
    "不要把参数整体或嵌套数组序列化成字符串；不要重复同一个键。"
)

# How much of the raw argument string to echo back in the error (a truncated
# ``write_file`` content can be tens of KB — the model does not need it back).
_RAW_PREVIEW_CAP = 160


def _state_messages(state: object) -> list:
    if isinstance(state, dict):
        return state.get("messages") or []
    return getattr(state, "messages", None) or []


def _tool_arg_keys(tools: Iterable[Any] | None) -> dict[str, frozenset[str]]:
    """``{tool_name: arg keys}`` for the tools whose schema is known up front.

    deepagents' framework tools (write_file / write_todos / task …) are registered
    by its own middleware and are not in this list — an unknown tool is accepted
    on repair and left to the tool node's own validation.
    """
    out: dict[str, frozenset[str]] = {}
    for t in tools or []:
        name = getattr(t, "name", None)
        if not name:
            continue
        try:
            args = getattr(t, "args", None) or {}
            keys = frozenset(str(k) for k in args.keys())
        except Exception:  # pragma: no cover - defensive: a tool with a weird schema
            continue
        if keys:
            out[str(name)] = keys
    return out


def _json_error(raw: str) -> str:
    """The stdlib decode error for ``raw`` — the actionable part of the hint."""
    try:
        json.loads(raw)
    except Exception as exc:  # JSONDecodeError / TypeError
        return str(exc)
    return "arguments did not decode to a JSON object"


def _repair_args(raw: object) -> dict[str, Any] | None:
    """Best-effort recovery of a tool-call argument dict from a malformed string.

    Order: strict ``json.loads`` (covers the rare invalid_tool_call whose text is
    valid JSON but not an object) → ``json_repair`` → one unwrap of a
    double-encoded JSON string. Anything that is not a non-empty dict is ``None``.
    """
    if isinstance(raw, dict):
        return raw or None
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    obj: Any = None
    try:
        obj = json.loads(text)
    except Exception:
        try:
            obj = json_repair.loads(text)
        except Exception:
            return None
    if isinstance(obj, str) and obj.strip().startswith("{"):
        # Double-encoded: the whole object was serialised as one JSON string.
        try:
            obj = json_repair.loads(obj)
        except Exception:
            return None
    if isinstance(obj, dict) and obj:
        return obj
    return None


def _nudge_count_this_turn(messages: list) -> int:
    """How many corrective ToolMessages were already issued since the last human
    turn. A fresh human message re-arms the (single) nudge — same contract as
    ``agent_factory._empty_retry_count``."""
    count = 0
    for m in messages:
        if isinstance(m, dict):
            role = m.get("type") or m.get("role")
            content = m.get("content")
        else:
            role = getattr(m, "type", None)
            content = getattr(m, "content", None)
        if role in ("human", "user"):
            count = 0
        elif role == "tool" and isinstance(content, str) and INVALID_ARGS_MARKER in content:
            count += 1
    return count


class LinsightInvalidToolCallRepairMiddleware(AgentMiddleware):
    """Turn ``AIMessage.invalid_tool_calls`` into executable calls (or a retry)."""

    def __init__(self, *, tools: Sequence[Any] | None = None, is_subagent: bool = False) -> None:
        super().__init__()
        self.tools = []  # registers no extra tools
        self.is_subagent = is_subagent
        self._arg_keys = _tool_arg_keys(tools)

    @property
    def name(self) -> str:
        # Role-distinct, stable name so the two instances (main vs subagent) never
        # collide in a shared middleware list.
        return f"LinsightInvalidToolCallRepair{'Sub' if self.is_subagent else 'Main'}"

    # ------------------------------------------------------------------ core

    def _plausible(self, name: str | None, args: dict[str, Any]) -> bool:
        """Reject a "repair" whose keys are not in the tool's schema — that is
        json_repair turning a broken string into key/value debris, and executing
        it would only trade one error for a stranger one."""
        known = self._arg_keys.get(name or "")
        if not known:
            return True
        return set(args.keys()) <= known

    def _process(self, state: Any) -> dict[str, Any] | None:
        messages = _state_messages(state)
        if not messages:
            return None
        ai = messages[-1]
        if not isinstance(ai, AIMessage):
            return None
        invalid = list(getattr(ai, "invalid_tool_calls", None) or [])
        if not invalid:
            return None

        repaired: list[dict[str, Any]] = []
        still_invalid: list[dict[str, Any]] = []
        tool_msgs: list[ToolMessage] = []
        for itc in invalid:
            name = itc.get("name") or "unknown"
            call_id = itc.get("id")
            raw = itc.get("args")
            args = _repair_args(raw)
            if args is not None and self._plausible(name, args) and call_id:
                repaired.append({"name": name, "args": args, "id": call_id, "type": "tool_call"})
                continue
            still_invalid.append(itc)
            if not call_id:
                # No id → nothing for a ToolMessage to answer; the request
                # serialiser drops id-less calls too, so there is nothing to pair.
                continue
            raw_text = "" if raw is None else str(raw)
            preview = raw_text[:_RAW_PREVIEW_CAP] + ("…" if len(raw_text) > _RAW_PREVIEW_CAP else "")
            error = _json_error(raw_text) if raw_text else "arguments were empty"
            content = _INVALID_ARGS_HINT.format(name=name, marker=INVALID_ARGS_MARKER, error=error)
            if preview:
                content += f"\n收到的参数开头：{preview}"
            tool_msgs.append(ToolMessage(content=content, name=name, tool_call_id=call_id, status="error"))

        update: dict[str, Any] = {}
        new_messages: list[Any] = []
        valid_calls = list(getattr(ai, "tool_calls", None) or [])
        if repaired:
            # Same id → the add_messages reducer replaces the AIMessage in place.
            new_ai = ai.model_copy(
                update={"tool_calls": [*valid_calls, *repaired], "invalid_tool_calls": still_invalid}
            )
            new_messages.append(new_ai)
            valid_calls = [*valid_calls, *repaired]
        new_messages.extend(tool_msgs)

        nudged = False
        if not valid_calls and tool_msgs:
            # Nothing executable is left this turn: hand the error back to the
            # model right away — but only once per user turn.
            if _nudge_count_this_turn(messages) == 0:
                update["jump_to"] = "model"
                nudged = True

        if new_messages:
            update["messages"] = new_messages
        logger.info(
            "BS_LINSIGHT_INVALID_TOOLCALL graph={} repaired={} unrepaired={} nudged={}",
            "sub" if self.is_subagent else "main",
            [c["name"] for c in repaired],
            [c.get("name") for c in still_invalid],
            nudged,
        )
        return update or None

    # ------------------------------------------------------------------ hooks

    @hook_config(can_jump_to=["model"])
    def after_model(self, state, runtime):
        return self._process(state)

    @hook_config(can_jump_to=["model"])
    async def aafter_model(self, state, runtime):
        return self._process(state)


def build_invalid_tool_call_repair_middleware(
    *, tools: Sequence[Any] | None = None, is_subagent: bool
) -> LinsightInvalidToolCallRepairMiddleware:
    """Construct a middleware instance (one per graph); ``tools`` is the graph's
    bound tool list, used only to sanity-check repaired argument keys."""
    return LinsightInvalidToolCallRepairMiddleware(tools=tools, is_subagent=is_subagent)
