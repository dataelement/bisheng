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

One instance per graph (main + researcher subagent), matching
``build_resilience_middleware`` — see ``build_tool_loop_breaker_middleware``.
"""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import ToolMessage
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


class LinsightToolLoopError(Exception):
    """Raised when one tool fails ``hard_limit`` times in a row.

    Carries the salvaged intermediate result so ``task_exec`` can surface it as a
    meaningful (partial) deliverable instead of a raw recursion error.
    """

    def __init__(self, *, tool_name: str | None, count: int, partial_result: str = "") -> None:
        self.tool_name = tool_name
        self.count = count
        self.partial_result = partial_result or ""
        super().__init__(
            f"Tool '{tool_name}' failed {count} times consecutively; aborting the task with a salvaged partial result."
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
    """Bound a same-tool consecutive-failure loop: soft nudge, then hard stop."""

    def __init__(self, *, soft_limit: int = 3, hard_limit: int = 8, is_subagent: bool = False) -> None:
        super().__init__()
        self.tools = []  # registers no extra tools
        self.soft_limit = max(1, soft_limit)
        self.hard_limit = max(self.soft_limit + 1, hard_limit)
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

    async def aafter_model(self, state, runtime):
        self._check_hard_limit(state)
        return None

    def after_model(self, state, runtime):
        self._check_hard_limit(state)
        return None


def build_tool_loop_breaker_middleware(linsight_conf, *, is_subagent: bool) -> LinsightToolLoopBreakerMiddleware:
    """Construct a middleware instance from ``LinsightConf`` (one per graph)."""
    return LinsightToolLoopBreakerMiddleware(
        soft_limit=getattr(linsight_conf, "tool_failure_soft_limit", 3),
        hard_limit=getattr(linsight_conf, "tool_failure_hard_limit", 8),
        is_subagent=is_subagent,
    )
