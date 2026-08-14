"""Tool-call loop breaker middleware for Linsight task mode (Layer 3).

Design: 灵思任务模式 write_file 死循环根因分析与优化方案 (Layer 3 / Layer 4).

A weak model can get stuck calling the same tool with the same broken arguments
forever — most notably ``write_file`` whose large ``content`` argument gets
truncated (``finish_reason=length``) and dropped by ``parse_partial_json``, so
every retry re-raises ``content: Field required``. Nothing in the stack counts
repeated identical tool failures, so the only backstop is ``recursion_limit``
(200) — ~19 minutes of wasted spinning ending in a raw ``GraphRecursionError``.

This ``AgentMiddleware`` bounds that loop, mirroring the built-in
``ToolCallLimitMiddleware`` pattern (raise from ``after_model`` — the one hook
whose exception propagates cleanly out of ``astream``, unlike ``wrap_tool_call``
whose raises are swallowed by ``ToolNode``):

- ``awrap_tool_call`` — SOFT nudge: once the same tool has failed ``soft_limit``
  times in a row, append a stronger corrective hint to the error ``ToolMessage``
  so a recoverable model can fix itself (e.g. "split the doc / put the full text
  in content").
- ``aafter_model`` — HARD stop: once the same tool has failed ``hard_limit``
  times in a row AND the model is STILL trying to call it, salvage the run's
  intermediate analysis + retrieved knowledge from the message history and raise
  ``LinsightToolLoopError(partial_result=...)``. ``task_exec`` renders that as a
  normal (COMPLETED) result with an apology preamble instead of a raw recursion
  error — the user still gets meaningful output.

A second, independent loop shape is bounded the same way (``reason="repeat"``): the
model re-submitting a BYTE-IDENTICAL tool call that keeps SUCCEEDING. The failure
tiers above are blind to it — they break on the first non-error result, and an
evicted "Tool result too large" message keeps its original ``status="success"``.
Its soft tier lives in ``wrap_model_call`` rather than ``wrap_tool_call``, because
deepagents' FilesystemMiddleware runs outside us and replaces evicted tool content
wholesale. See ``_identical_turn_run`` for the detection rules and the incident that
motivated them.

One instance per graph (main + researcher subagent), matching
``build_resilience_middleware`` — see ``build_tool_loop_breaker_middleware``.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import HumanMessage, ToolMessage
from loguru import logger

# The knowledge-search tool name (SearchKnowledgeBase). Kept as a local literal so
# this module does not import agent_factory (which imports this module).
_KB_TOOL_NAME = "search_knowledge_base"

# Salvage digest caps (D4-a: 精简结果 — analysis prioritized, retrieved chunks
# trimmed so we never dump dozens of pages of raw broker research verbatim).
_SALVAGE_ANALYSIS_CAP = 8000
_SALVAGE_KB_PER_CAP = 800
_SALVAGE_KB_TOTAL_CAP = 4000
_TRUNCATION_NOTE = "\n\n…（内容较长，已截断）"

# Repeating these is protocol, not a loop. ``ask_user`` parks on a langgraph
# interrupt: resuming from a checkpoint replays a same-shaped call, and treating that
# as a loop would kill a task that is merely waiting for its user.
_REPEAT_EXEMPT_TOOLS = frozenset({"ask_user"})

# Cheap, read-only or state-only tools. Repeating them wastes a turn but destroys
# nothing, and a nudge usually lands — ``resilience_middleware`` measured 10 of one
# researcher's 29 calls being nothing but ``write_todos``. They still get a ceiling
# (the multiplier below): an unbounded ls-loop would otherwise burn the turn budget.
_REPEAT_LENIENT_TOOLS = frozenset({"write_todos", "ls", "glob"})
_REPEAT_LENIENT_MULTIPLIER = 3

# The nudge carries the COUNT on purpose. With temperature=0 (the linsight default)
# and a tool_call_id that never changes, the offloaded ToolMessage is byte-identical
# every round, so context(n+1) is a deterministic function of context(n) — a fixed
# point that greedy decoding can never leave on its own. A monotonically changing
# line at the tail is what breaks the recurrence; restating the facts alone would not.
_REPEAT_HINT = (
    "⚠️ 你已经连续第 {count} 次提交**完全相同**的 {tools} 调用（参数逐字节一致），"
    "得到的也是同一个结果。再提交一次仍然不会有任何变化，请立刻改变做法：\n"
    "1) 若上一条工具结果提示「Tool result too large … saved in the filesystem at "
    "/large_tool_results/…」，说明结果**已经产生**、只是没有直接展示：用 read_file 读取那个路径"
    "取回内容，或用 grep 在 /large_tool_results/ 下按关键字定位。**不要重跑产生它的那次调用。**\n"
    "2) 若是代码执行：不要再提交同一段脚本。减少 print 的输出量（只打印你真正需要的部分），"
    "或把大段输出写进 scratch/ 下的文件，再用 read_file 分块读取。\n"
    "3) 若这一步确实无法推进，就跳过它，用已经掌握的材料完成交付，并在收尾时说明这一点。"
)


class LinsightToolLoopError(Exception):
    """Raised when one tool fails ``hard_limit`` times in a row, or when the model
    re-submits a byte-identical tool call ``repeat_hard_limit`` times in a row.

    Carries the salvaged intermediate result so ``task_exec`` can surface it as a
    meaningful (partial) deliverable instead of a raw recursion error.

    ``reason`` distinguishes the two causes so the user-facing preamble can state the
    right one. They are NOT interchangeable: a failure run means the tool kept
    erroring, a repeat run means it kept SUCCEEDING and the model ignored the result.
    Telling a user "模型未能正确调用写入工具" about a repeat loop is simply false.
    """

    def __init__(self, *, tool_name: str | None, count: int, partial_result: str = "", reason: str = "failure") -> None:
        self.tool_name = tool_name
        self.count = count
        self.partial_result = partial_result or ""
        self.reason = reason
        verb = "returned an identical result for" if reason == "repeat" else "failed"
        super().__init__(
            f"Tool '{tool_name}' {verb} {count} consecutive calls; aborting the task with a salvaged partial result."
        )


# ---------------------------------------------------------------------------
# Message-shape-tolerant helpers (dict OR message object; mirrors
# agent_factory._empty_retry_count's tolerance).
# ---------------------------------------------------------------------------


def _msg_fields(m: object) -> tuple[str | None, str | None, str | None, Any]:
    """Extract (role/type, name, status, content) from a message (dict or object)."""
    if isinstance(m, dict):
        return (m.get("type") or m.get("role"), m.get("name"), m.get("status"), m.get("content"))
    return (
        getattr(m, "type", None),
        getattr(m, "name", None),
        getattr(m, "status", None),
        getattr(m, "content", None),
    )


def _state_messages(state: object) -> list:
    if isinstance(state, dict):
        return state.get("messages") or []
    return getattr(state, "messages", None) or []


def _content_to_text(content: Any) -> str:
    """Flatten message content (str or multimodal list) to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "".join(parts)
    return "" if content is None else str(content)


def _cap(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + _TRUNCATION_NOTE


def _last_ai_message(messages: list) -> object | None:
    for m in reversed(messages):
        role, _, _, _ = _msg_fields(m)
        if role in ("ai", "assistant"):
            return m
    return None


def _tool_calls_of(message: object) -> list[dict]:
    if message is None:
        return []
    if isinstance(message, dict):
        calls = message.get("tool_calls")
    else:
        calls = getattr(message, "tool_calls", None)
    return calls or []


def _trailing_tool_failure_run(messages: list) -> tuple[str | None, int]:
    """(tool_name, count) of the trailing run of consecutive same-tool error
    ``ToolMessage``s.

    AIMessages (the tool-call producers, interleaved between each failure) are
    transparent; a non-error ToolMessage (a success), a different tool, or a
    human turn ends the run. Returns ``(None, 0)`` when the most recent tool
    result was not an error.
    """
    target: str | None = None
    count = 0
    for m in reversed(messages):
        role, name, status, _ = _msg_fields(m)
        if role in ("human", "user"):
            break
        if role in ("ai", "assistant"):
            continue  # tool-call producer — transparent to the run
        if role == "tool":
            if status != "error":
                break  # a success (or non-error) result ends the failure run
            if target is None:
                target, count = name, 1
            elif name == target:
                count += 1
            else:
                break  # a different tool's failure ends the same-tool run
            continue
        # Any other message kind (system, etc.): be conservative and stop.
        break
    return target, count


def _same_tool_streak(messages: list, tool_name: str | None) -> int:
    """Length of the trailing same-tool error run IF it matches ``tool_name``."""
    run_tool, run_count = _trailing_tool_failure_run(messages)
    return run_count if run_tool == tool_name else 0


# ---------------------------------------------------------------------------
# Identical-call detection (the "succeeded but got nowhere" loop)
# ---------------------------------------------------------------------------
#
# ``_trailing_tool_failure_run`` above only counts FAILURES. A tool that keeps
# succeeding while the model keeps re-sending the same arguments is invisible to it,
# and to every other guard in the stack: the turn budget bills each round as real
# work, and recursion_limit sits ~2500 steps away. Measured on 114, 2026-08-14: a
# kimi-k3 run re-sent a byte-identical bisheng_code_interpreter call 79 times over
# 78 minutes (13.8M input tokens) with zero todos advanced, and nothing stopped it.
#
# Why the whole turn and not just one call: parallel calls in one AIMessage are one
# unit of model intent. Comparing per-call would count a two-call turn as two.


def _args_digest(args: object) -> str:
    """Stable digest of tool-call arguments; never raises."""
    try:
        payload = json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        payload = repr(args)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _turn_fingerprint(message: object) -> tuple[tuple[str, str], ...] | None:
    """``(tool_name, args_digest)`` for every tool call in one AIMessage, sorted.

    ``None`` when the message carries no tool calls — the model is talking, which
    ends any repeat run.

    Deliberately EXCLUDES ``tool_call_id``. kimi-k3 (via tokenrouter) returns
    ``<tool_name>:<index-within-message>``, re-numbered per message and therefore
    constant across turns, while deepseek returns a unique ``call_<uuid>``. Folding
    the id in would make this detector fire on one vendor and never on the other.

    A set, not a list: two identical parallel calls in one turn contribute one
    element, so "twice in one turn" is not mistaken for "two turns".
    """
    calls = _tool_calls_of(message)
    if not calls:
        return None
    items: set[tuple[str, str]] = set()
    for call in calls:
        if isinstance(call, dict):
            name, args = call.get("name"), call.get("args")
        else:
            name, args = getattr(call, "name", None), getattr(call, "args", None)
        items.add((name or "", _args_digest(args if args is not None else {})))
    return tuple(sorted(items))


def _identical_turn_run(messages: list) -> tuple[tuple[tuple[str, str], ...] | None, int]:
    """``(fingerprint, count)`` of the trailing run of byte-identical model turns.

    ToolMessages are the CONSEQUENCE of a call and stay transparent. A human turn
    (new user input) or a text-only AI turn (the model changed course) ends the run.
    """
    latest: tuple[tuple[str, str], ...] | None = None
    count = 0
    for m in reversed(messages):
        role, _, _, _ = _msg_fields(m)
        if role in ("human", "user"):
            break
        if role not in ("ai", "assistant"):
            continue  # tool results are transparent to the run
        fingerprint = _turn_fingerprint(m)
        if fingerprint is None:
            break  # the model produced text — no longer repeating
        if latest is None:
            latest, count = fingerprint, 1
        elif fingerprint == latest:
            count += 1
        else:
            break
    if latest and any(name in _REPEAT_EXEMPT_TOOLS for name, _ in latest):
        return None, 0
    if latest and _is_pure_failure_run(messages, count):
        # A run where every result came back an error belongs to the FAILURE tier: it
        # has its own limits and its own user-facing copy ("模型未能正确调用工具").
        # Claiming it here would abort earlier than that tier intends AND attribute it
        # wrongly. This tier is for calls that SUCCEED and still get nowhere.
        return None, 0
    return latest, count


def _is_pure_failure_run(messages: list, count: int) -> bool:
    """True when the trailing identical run produced nothing but errors.

    ``count`` includes the newest AIMessage, whose tool has not run yet, so a fully
    failing run has at most ``count - 1`` error results.
    """
    _, failure_count = _trailing_tool_failure_run(messages)
    return failure_count >= count - 1


# ---------------------------------------------------------------------------
# Corrective hint + salvage assembly
# ---------------------------------------------------------------------------


def _corrective_hint(tool_name: str | None) -> str:
    if tool_name in ("write_file", "edit_file"):
        return (
            "⚠️ 你已连续多次调用 write_file 失败。最可能的原因是要写入的内容过长，导致 content 参数在传输中被截断、"
            "解析后丢失。请立刻改用「分段写入」：先用 write_file 写入文档的第一部分（务必在**同一次**调用里把该部分的"
            "完整文本放进 content 参数），随后用 edit_file 逐段追加后续内容。不要再用空参数或仅 file_path 调用 write_file。"
        )
    if tool_name:
        return (
            f"⚠️ 你已连续多次调用 {tool_name} 失败。请检查工具参数（尤其是必填项是否完整），修正后再试；"
            "不要重复完全相同的错误调用。若无法修正，请换一种方式完成该步骤。"
        )
    return "⚠️ 你已连续多次工具调用失败。请修正参数后再试，不要重复相同的错误调用。"


def _digest_snippets(snippets: list[str], per_cap: int, total_cap: int) -> str:
    out: list[str] = []
    used = 0
    for snip in snippets:
        if used >= total_cap:
            out.append("…（其余检索结果已省略）")
            break
        chunk = _cap(snip, min(per_cap, total_cap - used))
        out.append(chunk)
        used += len(chunk)
    return "\n\n---\n\n".join(c for c in out if c)


def assemble_partial_result(messages: list) -> str:
    """Salvage the run's intermediate analysis + retrieved knowledge as markdown.

    Prioritizes the model's own analysis text (AIMessage content = 分析结论);
    appends a trimmed digest of ``search_knowledge_base`` results (检索到的知识).
    Returns an empty string when nothing salvageable exists (caller falls back).
    """
    analyses: list[str] = []
    kb: list[str] = []
    for m in messages:
        role, name, status, content = _msg_fields(m)
        text = _content_to_text(content).strip()
        if not text:
            continue
        if role in ("ai", "assistant"):
            analyses.append(text)
        elif role == "tool" and name == _KB_TOOL_NAME and status != "error":
            kb.append(text)

    parts: list[str] = []
    if analyses:
        parts.append("## 已完成的分析\n\n" + _cap("\n\n".join(analyses), _SALVAGE_ANALYSIS_CAP))
    if kb:
        digest = _digest_snippets(kb, _SALVAGE_KB_PER_CAP, _SALVAGE_KB_TOTAL_CAP)
        if digest:
            parts.append("## 检索到的关键资料（摘要）\n\n" + digest)
    return "\n\n".join(parts).strip()


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class LinsightToolLoopBreakerMiddleware(AgentMiddleware):
    """Bound two shapes of tool loop: consecutive FAILURES, and byte-identical
    REPEATS that keep succeeding. Both go soft nudge first, then hard stop."""

    def __init__(
        self,
        *,
        soft_limit: int = 3,
        hard_limit: int = 8,
        repeat_soft_limit: int = 3,
        repeat_hard_limit: int = 8,
        is_subagent: bool = False,
    ) -> None:
        super().__init__()
        self.tools = []  # registers no extra tools
        self.soft_limit = max(1, soft_limit)
        self.hard_limit = max(self.soft_limit + 1, hard_limit)
        # <= 0 disables that tier outright. This is the rollback switch: both values
        # come from LinsightConf, so a bad rollout is a DB config change (<=100s)
        # rather than a redeploy.
        self.repeat_soft_limit = max(0, repeat_soft_limit)
        self.repeat_hard_limit = 0 if repeat_hard_limit <= 0 else max(self.repeat_soft_limit + 1, repeat_hard_limit)
        self.is_subagent = is_subagent

    @property
    def name(self) -> str:
        # Role-distinct, stable name so the two instances (main vs subagent) never
        # collide in a shared middleware list.
        return f"LinsightToolLoopBreaker{'Sub' if self.is_subagent else 'Main'}"

    async def awrap_tool_call(self, request, handler):
        """SOFT nudge: append a corrective hint once a tool keeps failing."""
        response = await handler(request)
        # Only ordinary tool FAILURES are actionable. A Command (handoff), a
        # success, or an interrupt (which raises out of ``handler`` and never
        # reaches here) all pass through untouched.
        if not isinstance(response, ToolMessage) or response.status != "error":
            return response
        tool_call = request.tool_call or {}
        tool_name = tool_call.get("name")
        # This failing result is not yet in state; count prior same-tool failures + 1.
        current = _same_tool_streak(_state_messages(request.state), tool_name) + 1
        if current >= self.soft_limit:
            hint = _corrective_hint(tool_name)
            base = response.content if isinstance(response.content, str) else _content_to_text(response.content)
            return response.model_copy(update={"content": f"{base}\n\n{hint}"})
        return response

    def _check_hard_limit(self, state) -> None:
        """Raise ``LinsightToolLoopError`` iff a tool has failed ``hard_limit``
        times in a row AND the model is STILL trying to call that same tool.

        The second guard is essential: without it, a model that recovered on the
        turn AFTER the streak (a plain text answer, or switching tools) would be
        wrongly aborted because the trailing ToolMessage is still an error.
        """
        messages = _state_messages(state)
        last_ai = _last_ai_message(messages)
        pending = _tool_calls_of(last_ai)
        if not pending:
            return  # model produced a final answer / stopped looping — let it complete
        run_tool, run_count = _trailing_tool_failure_run(messages)
        if run_tool is None or run_count < self.hard_limit:
            return
        if not any(tc.get("name") == run_tool for tc in pending):
            return  # model switched to a different tool — give it a chance
        salvage = assemble_partial_result(messages)
        logger.warning(
            "[linsight-toolloop] '{}' failed {} times consecutively ({}); aborting with "
            "{} chars of salvaged partial result",
            run_tool,
            run_count,
            self.name,
            len(salvage),
        )
        raise LinsightToolLoopError(tool_name=run_tool, count=run_count, partial_result=salvage)

    # --- identical-repeat tier ------------------------------------------------

    def _repeat_nudge(self, request):
        """SOFT tier: append a counted corrective instruction to THIS request only.

        Why ``wrap_model_call`` and not ``wrap_tool_call``: deepagents'
        ``FilesystemMiddleware`` sits OUTSIDE every bisheng middleware, and its
        eviction path REPLACES a large ToolMessage's content wholesale. A hint
        appended to the tool result would therefore be discarded in exactly the
        case that needs it most. Appending to the request message list is ephemeral
        (never enters graph state) and mirrors ``_with_wrap_up_nudge`` in
        ``resilience_middleware``, which is already proven in production. It also
        keeps the cached system-prompt prefix intact — writing this into the system
        message would invalidate the prompt cache on every single turn.
        """
        if not self.repeat_soft_limit:
            return request
        # Scan graph state, NOT ``request.messages``: the outer resilience middleware
        # appends a wrap-up HumanMessage during soft landing, and a human turn ends a
        # repeat run — reading the request list would silently disable this detector
        # exactly while the run is already in trouble.
        messages = _state_messages(getattr(request, "state", None)) or list(getattr(request, "messages", []) or [])
        fingerprint, count = _identical_turn_run(messages)
        if fingerprint is None or count < self.repeat_soft_limit:
            return request
        tools = sorted({name for name, _ in fingerprint})
        logger.warning(
            "[linsight-toolloop] identical tool call repeated {}x ({}) ({}); injecting corrective nudge",
            count,
            ",".join(tools),
            self.name,
        )
        hint = _REPEAT_HINT.format(count=count, tools="、".join(tools))
        return request.override(messages=[*request.messages, HumanMessage(content=hint)])

    async def awrap_model_call(self, request, handler):
        return await handler(self._repeat_nudge(request))

    def wrap_model_call(self, request, handler):
        return handler(self._repeat_nudge(request))

    def _check_repeat_limit(self, state) -> None:
        """HARD tier for byte-identical repeats that keep SUCCEEDING.

        ``_check_hard_limit`` cannot see these: it breaks on the first non-error
        result, and an evicted tool message keeps its original ``status="success"``.
        """
        if not self.repeat_hard_limit:
            return
        messages = _state_messages(state)
        fingerprint, count = _identical_turn_run(messages)
        if fingerprint is None:
            return  # model is talking, or the run involves an exempt tool
        names = {name for name, _ in fingerprint}
        limit = self.repeat_hard_limit
        if names <= _REPEAT_LENIENT_TOOLS:
            limit *= _REPEAT_LENIENT_MULTIPLIER
        if count < limit:
            return
        salvage = assemble_partial_result(messages)
        logger.warning(
            "[linsight-toolloop] identical tool call repeated {}x ({}) ({}); aborting with "
            "{} chars of salvaged partial result",
            count,
            ",".join(sorted(names)),
            self.name,
            len(salvage),
        )
        raise LinsightToolLoopError(tool_name=sorted(names)[0], count=count, partial_result=salvage, reason="repeat")

    def _check_limits(self, state) -> None:
        self._check_hard_limit(state)  # consecutive same-tool FAILURES
        self._check_repeat_limit(state)  # consecutive byte-identical calls

    async def aafter_model(self, state, runtime):
        self._check_limits(state)
        return None

    def after_model(self, state, runtime):
        self._check_limits(state)
        return None


def build_tool_loop_breaker_middleware(linsight_conf, *, is_subagent: bool) -> LinsightToolLoopBreakerMiddleware:
    """Construct a middleware instance from ``LinsightConf`` (one per graph)."""
    return LinsightToolLoopBreakerMiddleware(
        soft_limit=getattr(linsight_conf, "tool_failure_soft_limit", 3),
        hard_limit=getattr(linsight_conf, "tool_failure_hard_limit", 8),
        repeat_soft_limit=getattr(linsight_conf, "tool_repeat_soft_limit", 3),
        repeat_hard_limit=getattr(linsight_conf, "tool_repeat_hard_limit", 8),
        is_subagent=is_subagent,
    )
