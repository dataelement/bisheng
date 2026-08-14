"""Model-call resilience middleware for Linsight task mode.

Design: 灵思LLM容错与失败态友好交互. A single ``AgentMiddleware`` injected into
BOTH the main deepagents graph and the researcher subagent. It wraps the
(already ``bind_tools``'d) model handler via the native ``awrap_model_call``
hook — so it never touches the model object and never breaks the tool-binding
chain (unlike a ``BaseChatModel`` wrapper or ``.with_retry()``).

Per-call behaviour, keyed off ``classify_behavior`` (vendor-agnostic):

- ``RETRYABLE`` (transient) → exponential-backoff retry (Layer A).
- ``FAIL_FAST`` (quota / auth)  → re-raise → clean classified task failure.
- ``DEGRADABLE`` (content filter / other non-retryable) and retry-exhausted:
    * subagent   → return a synthetic ``AIMessage`` so the subagent ends
      gracefully and the PARENT task continues with the remaining steps
      (Layer B — the multi-step "single failure ≠ whole-task failure" win).
    * main graph → re-raise → clean classified task failure. A main-agent
      content-filter hit happens mid-reasoning with no usable plan, so a
      no-tool-call synthetic message would merely end the loop with junk;
      failing cleanly routes to the friendly classified error UI instead
      (see the plan's honest caveat).

A per-instance degrade budget caps runaway skipping inside one task; over
budget → re-raise. Each graph gets its OWN instance (main vs subagent), so the
budgets are isolated and the ``is_subagent`` flag is known at construction time
(no runtime namespace sniffing needed).
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable

from langchain.agents.middleware._retry import calculate_delay
from langchain.agents.middleware.types import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from loguru import logger

from bisheng.common.services.llm_error_classifier import Behavior, classify_behavior

# Synthetic reply substituted for a degraded subagent step. Read by the PARENT
# planner as a control note ("this leg failed — continue with what you have"),
# NOT as a valid finding. Kept bilingual + instruction-flavored so it works
# regardless of the task language: the model is told to note the gap in the
# USER's language and not echo this notice verbatim, so an English deliverable
# never leaks an untranslated Chinese banner.
_DEGRADE_MESSAGE = (
    "⚠️ 本步因触发模型服务商安全策略或多次调用失败已被跳过，结果不完整。"
    "请基于其他已获得的信息继续完成任务，并在最终交付物中用用户的语言简要说明此处缺失，"
    "不要原样输出本提示。\n"
    "[System note] This step was skipped due to a provider safety block or repeated "
    "call failures; its result is incomplete. Continue with the information already "
    "gathered, briefly acknowledge the gap in the final deliverable using the user's "
    "language, and do not echo this notice verbatim."
)


# Layer 2 (截断即时检测): a corrective nudge injected when a model call is cut off
# by finish_reason=length WHILE emitting a tool call — the exact failure behind the
# write_file "content: Field required" loop (a huge content arg gets truncated and
# parse_partial_json drops the incomplete key). Injected as an ephemeral extra
# message on the RETRY request only (not persisted to graph state), telling the
# model to write in smaller parts. Bounded by ``truncation_retry_limit``; if still
# truncating, the (truncated) response is returned and the L3 tool-loop breaker /
# L4 recursion ceiling takes over.
_TRUNCATION_NUDGE = (
    "⚠️ 你上一次的输出因过长被截断（finish_reason=length），导致工具调用的参数不完整、无法执行。"
    "请把要写入的内容拆成多个较小的部分：先用 write_file 写入第一部分（务必在同一次调用里放入该部分的完整 content），"
    "再用 edit_file 逐段追加后续内容；或显著缩短单次写入的内容量。不要重复相同的超长调用。"
)

# finish/stop reasons that mean "output was cut off by the max-token limit",
# across OpenAI-compatible ("length") and Anthropic ("max_tokens") vendors.
_TRUNCATION_FINISH_REASONS = frozenset({"length", "max_tokens", "max_output_tokens"})


# ---------------------------------------------------------------------------
# Incomplete-stream guard
#
# A provider can close the SSE stream mid-turn WITHOUT raising anything: httpx
# sees a clean EOF, the openai SDK simply stops yielding chunks, and langchain
# hands back whatever it had accumulated. Nothing in the retry path above ever
# runs, because nothing failed.
#
# Measured on 114 (2026-08-13, grok4.6 via tokenrouter, 147k-token context): the
# model emitted one line of narration ("正在撰写完整参数清单与 D2 数据表。") and the
# stream closed before the ``write_file`` call it was about to make. The result
# was an AIMessage with NO tool calls — which deepagents reads as "the agent is
# done" — so a run with 3 of its 5 steps still pending completed "successfully"
# with that narration as its final answer and as its only deliverable.
#
# Fingerprint of a stream that never finished (all three must hold):
#   - no finish_reason / stop_reason — a completed OpenAI-compatible or Anthropic
#     stream always carries one;
#   - no input token usage — the usage chunk is the last thing a completed stream
#     sends, and ``input_tokens`` is never legitimately 0 (a provider that omits
#     usage entirely still reports finish_reason, so this stays a confirmation
#     signal, never the sole trigger);
#   - no tool call at all — the only shape that silently routes the graph to END.
#     A stream cut mid-tool-call is deliberately EXCLUDED: the graph keeps running
#     (the tool errors out and the L2 truncation nudge / L3 loop breaker take
#     over), so it is neither silent nor worth re-sending a six-figure-token
#     request over.
# ---------------------------------------------------------------------------


class IncompleteStreamError(ConnectionError):
    """The provider closed the response stream before the model finished its turn.

    Subclasses ``ConnectionError`` deliberately — that IS what happened at the
    transport layer, and it makes ``classify_behavior`` bucket this as RETRYABLE and
    ``label_error`` render the network-timeout card, without teaching the shared
    classifier about a Linsight-only exception type.
    """


# Retries for an incomplete stream. Deliberately small and SEPARATE from both the
# exception-retry and truncation budgets: every attempt re-sends the entire request
# (147k input tokens in the measured case), so this spends a bounded amount of money
# to avoid silently truncating the run.
_INCOMPLETE_STREAM_RETRY_LIMIT = 2


# ---------------------------------------------------------------------------
# Turn budget + soft landing
#
# The run's real gate is a MODEL-TURN budget, not LangGraph's ``recursion_limit``
# (which counts super-steps: ~4 per turn, so its number never matches operator
# intuition). Counting here — inside ``wrap_model_call`` — is deliberate: wrap
# hooks are NOT compiled into graph nodes, so this costs zero super-steps.
# langchain's own ``ModelCallLimitMiddleware`` implements before_model +
# after_model, which would add two nodes per turn (4 -> 6 super-steps) and shrink
# the usable turn count instead of protecting it; it also hard-jumps to END,
# giving the model no chance to write its deliverable.
#
# Instead the budget lands in three stages, so the run ENDS ITSELF cleanly rather
# than being cut down mid-thought and salvaged afterwards:
#   1. nudge      — tell the model to wrap up while it still has every tool;
#   2. write-only — narrow the tool set to the ones that produce deliverables;
#   3. no tools   — nothing is offered to the model, and ``wrap_tool_call`` refuses
#                   anything exploratory it calls anyway, so the only way forward
#                   is a text answer: the graph reaches END on its own and the run
#                   completes normally (no apology path).
#
# Stages 1-2 are hints — they shape ``request.tools``, which only controls what the
# model is TOLD it has. Stage 3 needs the tool-layer refusal to actually bind; see
# ``_POST_BUDGET_ALLOWED_TOOLS``.
# ---------------------------------------------------------------------------

# Turns left at which stage 2 kicks in (stage 1 is configurable, stage 3 is zero).
_WRITE_ONLY_TURNS_LEFT = 2

# Tools still offered in stage 2: the ones that put a deliverable on disk.
_DELIVERABLE_TOOLS = frozenset({"write_file", "edit_file", "export_docx", "export_pdf"})

# Tools that remain EXECUTABLE after the budget is spent (stage 3's hard stop).
#
# Narrowing ``request.tools`` alone cannot enforce a budget: with an empty list
# langchain skips ``bind_tools`` entirely (factory.py — ``if final_tools:``), so the
# request merely omits the tools parameter, while ToolNode still holds every tool
# from compile time. A model that has seen hundreds of tool calls in its history
# keeps emitting them and they keep executing — measured on 114: a 6-turn budget
# ran 8 turns. Blocking at ``wrap_tool_call`` is the enforceable layer, because it
# runs INSIDE ToolNode where the model cannot route around it.
#
# ``write_todos`` is allowed through deliberately: it is the only channel that
# syncs task progress to the UI, so blocking it would leave a finished run
# displaying "3/5". The deliverable writers are allowed for the obvious reason —
# the whole point of landing softly is to still produce the file.
_POST_BUDGET_ALLOWED_TOOLS = _DELIVERABLE_TOOLS | {"write_todos"}

# LangGraph's checkpoint-namespace level separator, mirroring
# ``langgraph._internal._constants.NS_SEP``. Re-declared rather than imported: the
# value is part of the checkpoint wire format and far more stable than the private
# module path. Pinned by ``test/linsight/test_subagent_ns_contract.py``.
_NS_SEP = "|"

# Upper bound on live turn-budget buckets (see ``_budget_key``). Observed concurrent
# delegations are single-digit; 128 is far above any real plan, and eviction is LRU
# so an active bucket can never be pushed out by stale ones.
_BUDGET_BUCKETS_MAX = 128

# Tool calls that are PURE STATE MAINTENANCE: they move no work forward, they only
# republish the plan. deepagents injects ``TodoListMiddleware`` into every subagent
# unconditionally (``deepagents/graph.py:643-651``) — it is not part of the business
# tool subset ``agent_factory._subagent_tools`` builds. Measured on v2.6.0-fix2: 10 of
# a researcher's 29 model calls produced ``write_todos`` and nothing else, i.e. a third
# of a 30-turn budget bought zero research. Those turns are refunded instead.
_STATE_ONLY_TOOLS = frozenset({"write_todos"})

# Refunds are CAPPED. Uncapped, a model looping on ``write_todos`` would never advance
# the counter, the soft-landing ladder would never fire, and the run would die on
# GraphRecursionError instead — the exact failure ``_resolve_recursion_limit`` exists
# to prevent. The L3 tool-loop breaker cannot cover this either: it trips on tool
# FAILURES, and ``write_todos`` succeeds every time.
_MAX_STATE_ONLY_REFUNDS = 10

_BUDGET_SPENT_TOOL_REPLY = (
    "⚠️ 本次任务的模型调用次数预算已用尽，{tool_name} 未被执行。"
    "请立即用已经掌握的材料完成交付：先用 write_file 把最终成果写入 output/ 目录下的交付文件，"
    "再直接用文字给出结论。不要再调用任何检索、读取或代码执行类工具。"
)

_WRAP_UP_NUDGE = (
    "⚠️ 本次任务的模型调用次数预算即将耗尽（剩余约 {remaining} 次）。请立即停止新的探索性调用，"
    "用已经掌握的材料完成交付：先把最终成果写入 output/ 目录下的交付文件，再用一段话说明结论。"
    "不要再开启新的分支任务或反复验证。"
)

_LAST_CHANCE_NUDGE = (
    "⚠️ 这是最后的收尾机会（剩余约 {remaining} 次模型调用），当前只提供写文件/导出工具。"
    "请立刻把已完成的内容写入 output/ 目录下的交付文件，不要再做任何检查、验证或探索。"
)


def _with_wrap_up_nudge(request: ModelRequest, template: str, remaining: int) -> ModelRequest:
    """Append the wrap-up instruction to THIS request only (never to graph state).

    Same ephemeral shape as ``_with_truncation_nudge``: appended at the tail of
    the message list (the strongest position) rather than into the system
    message, which would change the cached prefix on every single turn.
    """
    return request.override(messages=[*request.messages, HumanMessage(content=template.format(remaining=remaining))])


def _only_deliverable_tools(request: ModelRequest) -> ModelRequest:
    """Narrow the bound tools to the deliverable writers (stage 2)."""
    kept = [t for t in request.tools if getattr(t, "name", None) in _DELIVERABLE_TOOLS]
    return request.override(tools=kept)


def _response_ai_message(response: object) -> AIMessage | None:
    """Extract the model's ``AIMessage`` from a handler result (ModelResponse | AIMessage)."""
    if isinstance(response, AIMessage):
        return response
    result = getattr(response, "result", None)
    if result:
        for m in reversed(result):
            if isinstance(m, AIMessage):
                return m
    return None


def _is_truncated_tool_call(response: object) -> bool:
    """True when the model was cut off by the token limit WHILE emitting a tool call.

    Vendor-agnostic: keys purely off ``finish_reason``/``stop_reason`` + the presence
    of a (possibly malformed) tool-call attempt on the message. A truncated tool call
    is exactly what surfaces as ``content: Field required`` downstream.
    """
    ai = _response_ai_message(response)
    if ai is None:
        return False
    meta = getattr(ai, "response_metadata", None) or {}
    finish = meta.get("finish_reason") or meta.get("stop_reason")
    if finish not in _TRUNCATION_FINISH_REASONS:
        return False
    return bool(getattr(ai, "tool_calls", None)) or bool(getattr(ai, "invalid_tool_calls", None))


def _is_incomplete_stream_response(response: object) -> bool:
    """True when the provider closed the stream before the model finished its turn.

    Vendor-agnostic, and deliberately a three-way conjunction — see the
    ``IncompleteStreamError`` block above for why each conjunct is needed and why a
    stream cut mid-tool-call is excluded.
    """
    ai = _response_ai_message(response)
    if ai is None:
        return False
    meta = getattr(ai, "response_metadata", None) or {}
    # No provider metadata at all → not a provider stream (a synthetic/degraded
    # message, or a non-streaming shim). langchain fills model_name from the very
    # first chunk, so a real stream — finished or cut off — always carries something.
    if not meta:
        return False
    if meta.get("finish_reason") or meta.get("stop_reason"):
        return False
    if getattr(ai, "tool_calls", None) or getattr(ai, "invalid_tool_calls", None):
        return False
    usage = getattr(ai, "usage_metadata", None) or {}
    return not usage.get("input_tokens")


def _with_truncation_nudge(request: ModelRequest) -> ModelRequest:
    """A new request with the corrective nudge appended (ephemeral — retry only)."""
    return request.override(messages=[*request.messages, HumanMessage(content=_TRUNCATION_NUDGE)])


def _is_state_only_turn(response: object) -> bool:
    """True iff this model call produced ONLY pure state-maintenance tool calls.

    Deliberately strict — a turn is refunded only when it demonstrably moved nothing
    forward. Everything else still costs a turn:

    - no ``AIMessage`` at all → unknown shape, stay conservative;
    - no tool calls (a text-only close-out) → that IS the run's real last turn, and
      refunding it would keep the ladder from ever reaching stage 3;
    - any invalid/malformed tool call → the model attempted real work and failed;
    - ``write_todos`` alongside any other tool → real work happened this turn.
    """
    ai = _response_ai_message(response)
    if ai is None:
        return False
    if getattr(ai, "invalid_tool_calls", None):
        return False
    calls = getattr(ai, "tool_calls", None) or []
    if not calls:
        return False
    names = {tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None) for tc in calls}
    return names <= _STATE_ONLY_TOOLS


def _summarize_tool_calls(ai: AIMessage) -> list[str]:
    """Compact ``name(argkey1,argkey2)`` per tool call — argument KEYS only, never
    VALUES, so a large ``write_file`` ``content`` is never dumped into the log. A
    truncated/malformed call shows as a missing key (``write_file(file_path)`` — no
    ``content``) or ``name(INVALID)``; that is exactly the diagnostic signal for the
    write_file loop.
    """
    summary: list[str] = []
    for tc in getattr(ai, "tool_calls", None) or []:
        name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
        args = (tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", None)) or {}
        keys = ",".join(sorted(args.keys())) if isinstance(args, dict) else ""
        summary.append(f"{name}({keys})")
    for tc in getattr(ai, "invalid_tool_calls", None) or []:
        name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
        summary.append(f"{name}(INVALID)")
    return summary


def _log_call_diagnostics(response: object, *, is_subagent: bool) -> None:
    """One structured, greppable line per model call — so the write_file truncation
    loop can be diagnosed from stdout even though task-mode calls are not persisted
    to ``llm_call_log`` (that audit is workflow-only, and lacks finish_reason / tool
    args anyway). Captures finish_reason, token usage, and the tool-call arg KEYS
    (never values). Best-effort: never raises, never affects the model call.
    """
    try:
        ai = _response_ai_message(response)
        if ai is None:
            return
        meta = getattr(ai, "response_metadata", None) or {}
        finish = meta.get("finish_reason") or meta.get("stop_reason")
        usage = getattr(ai, "usage_metadata", None) or {}
        content = ai.content if isinstance(ai.content, str) else ""
        logger.info(
            "BS_LINSIGHT_LLM_CALL graph={} finish_reason={} in_tokens={} out_tokens={} "
            "content_len={} tool_calls={} truncated={}",
            "sub" if is_subagent else "main",
            finish,
            usage.get("input_tokens"),
            usage.get("output_tokens"),
            len(content),
            _summarize_tool_calls(ai) or "-",
            _is_truncated_tool_call(response),
        )
    except Exception as e:  # pragma: no cover - observability must never break the call
        logger.debug(f"[linsight] call-diagnostics logging failed: {e}")


class LinsightModelResilienceMiddleware(AgentMiddleware):
    """Retry transient model failures; degrade or fail cleanly on the rest."""

    def __init__(
        self,
        *,
        max_retries: int = 3,
        initial_delay: float = 5.0,
        max_delay: float = 60.0,
        backoff_factor: float = 2.0,
        jitter: bool = True,
        max_degrade: int = 3,
        truncation_retry_limit: int = 2,
        is_subagent: bool = False,
        turn_limit: int = 115,
        soft_landing_turns: int = 8,
        budget_sink: dict | None = None,
    ) -> None:
        super().__init__()
        self.tools = []  # registers no extra tools
        self.max_retries = max(0, max_retries)
        self.initial_delay = max(0.0, initial_delay)
        self.max_delay = max(0.0, max_delay)
        self.backoff_factor = max(0.0, backoff_factor)
        self.jitter = jitter
        self.max_degrade = max(0, max_degrade)
        self.truncation_retry_limit = max(0, truncation_retry_limit)
        self.is_subagent = is_subagent
        # KNOWN GAP (not fixed here to keep the backport surface small): this counter
        # has the same cross-``task``-call sharing problem the turn budget had — every
        # delegation shares one ``max_degrade`` allowance. Bucket it on ``_budget_key``
        # when touching this next.
        self._degrade_count = 0
        # Turn budget, bucketed per graph RUN rather than per middleware instance:
        #
        #   - main graph → exactly one bucket. One compiled Pregel loop, one allowance;
        #     ``budget_sink`` semantics unchanged.
        #   - subagent   → ONE BUCKET PER ``task`` TOOL CALL. deepagents compiles the
        #     researcher ONCE (``subagents.py:584``) and every ``task`` call re-enters
        #     that same runnable, so a single counter was silently shared: two parallel
        #     researchers burned one 30-turn allowance between them and the second one
        #     started already inside the soft-landing zone (measured, v2.6.0-fix2).
        #
        # Either way the budget resets when the agent is rebuilt — an ask_user resume
        # grants a fresh allowance, matching LangGraph's own
        # ``stop = step + recursion_limit + 1`` recomputation on resume.
        self.turn_limit = max(1, turn_limit)
        self.soft_landing_turns = max(0, soft_landing_turns)
        self._turns: OrderedDict[str, int] = OrderedDict()
        self._refunds: OrderedDict[str, int] = OrderedDict()
        # Optional shared dict the task executor reads after the run to tell the
        # user their result was wrapped up early.
        self._budget_sink = budget_sink

    @property
    def name(self) -> str:
        # Stable, role-distinct name so the two instances never collide if a
        # future refactor ever places them in one middleware list.
        return f"LinsightModelResilience{'Sub' if self.is_subagent else 'Main'}"

    def _delay(self, attempt: int) -> float:
        return calculate_delay(
            attempt,
            backoff_factor=self.backoff_factor,
            initial_delay=self.initial_delay,
            max_delay=self.max_delay,
            jitter=self.jitter,
        )

    def _budget_key(self, request: object) -> str:
        """Which turn-budget bucket this model/tool call belongs to.

        Main graph → always the single default bucket. The main graph is ONE compiled
        Pregel loop with ONE allowance, and its node namespace (``model:<uuid>``)
        carries a fresh task id every turn, so bucketing it would hand it a brand-new
        budget on every single call.

        Subagent → the parent namespace of the current node. LangGraph gives each
        ``task`` tool call its own PUSH task (one ``Send`` per tool call, whose task id
        includes the Send index), and every node inside the resulting subgraph run is
        namespaced ``<that tools task ns>|<node>:<node task id>``. Dropping the last
        segment therefore yields a key that is CONSTANT across all turns of one
        ``task`` call and DISTINCT between concurrent ones — pinned by
        ``test/linsight/test_subagent_ns_contract.py``.

        Anything unexpected (no runtime, as in unit tests or non-graph callers; or a
        flat namespace, meaning the subagent graph ran un-nested) falls back to the
        shared bucket, which is exactly the pre-fix behaviour — never worse.
        """
        if not self.is_subagent:
            return ""
        runtime = getattr(request, "runtime", None)
        info = getattr(runtime, "execution_info", None)
        ns = getattr(info, "checkpoint_ns", None)
        if not isinstance(ns, str) or _NS_SEP not in ns:
            return ""
        return ns.rsplit(_NS_SEP, 1)[0]

    def _turns_used(self, key: str = "") -> int:
        return self._turns.get(key, 0)

    def _bump_turn(self, key: str) -> int:
        """Count one turn against ``key`` and return the new total (LRU-bounded)."""
        used = self._turns.pop(key, 0) + 1
        self._turns[key] = used  # re-insert → most-recently-used tail
        while len(self._turns) > _BUDGET_BUCKETS_MAX:
            evicted, _ = self._turns.popitem(last=False)
            self._refunds.pop(evicted, None)
        return used

    def _refund_turn(self, key: str) -> None:
        """Give a pure state-maintenance turn its budget back (bounded per bucket)."""
        used = self._turns.get(key, 0)
        if used <= 0:
            return
        if self._refunds.get(key, 0) >= _MAX_STATE_ONLY_REFUNDS:
            return
        self._turns[key] = used - 1
        self._refunds[key] = self._refunds.get(key, 0) + 1

    @property
    def _turn_count(self) -> int:
        """Turns used in the DEFAULT bucket — i.e. the whole budget for the main graph.

        Read-only alias kept so main-graph call sites and existing tests read
        unchanged; subagent buckets must be read via ``_turns_used(key)``.
        """
        return self._turns_used("")

    def _apply_turn_budget(self, request: ModelRequest) -> tuple[ModelRequest, str]:
        """Count this turn and apply the soft-landing stage it falls into.

        Called ONCE per ``wrap_model_call`` — i.e. once per model node execution.
        The retry loops below re-enter ``handler`` without re-entering this, so a
        transient retry or a truncation nudge never burns turn budget.

        Returns the (possibly nudged) request together with the budget key it was
        counted against, so the caller can refund a pure state-maintenance turn once
        the response makes that knowable.
        """
        key = self._budget_key(request)
        graph = "sub" if self.is_subagent else "main"
        count = self._bump_turn(key)
        remaining = self.turn_limit - count
        if remaining > self.soft_landing_turns:
            return request, key

        self._mark_soft_landing()
        if remaining <= 0:
            # No tools at all: the model can only produce a text answer, which
            # routes the graph straight to END. This is what turns "budget
            # exhausted" into a normal completion instead of a recursion abort.
            logger.warning(
                "[linsight-turn-budget] graph={} key={} turn {}/{} — budget exhausted, forcing a text-only close-out",
                graph,
                key or "-",
                count,
                self.turn_limit,
            )
            return _with_wrap_up_nudge(request, _LAST_CHANCE_NUDGE, 0).override(tools=[]), key
        if remaining <= _WRITE_ONLY_TURNS_LEFT:
            logger.warning(
                "[linsight-turn-budget] graph={} key={} turn {}/{} — {} left, narrowing to deliverable tools",
                graph,
                key or "-",
                count,
                self.turn_limit,
                remaining,
            )
            return (
                _only_deliverable_tools(_with_wrap_up_nudge(request, _LAST_CHANCE_NUDGE, remaining)),
                key,
            )
        logger.info(
            "[linsight-turn-budget] graph={} key={} turn {}/{} — {} left, nudging the model to wrap up",
            graph,
            key or "-",
            count,
            self.turn_limit,
            remaining,
        )
        return _with_wrap_up_nudge(request, _WRAP_UP_NUDGE, remaining), key

    def _budget_blocked_reply(self, request) -> ToolMessage | None:
        """Refuse an exploratory tool call once the turn budget is spent.

        Returns the stand-in ToolMessage to hand back instead of running the tool,
        or None to let the call through. This middleware is FIRST in the stack, so
        its wrap_tool_call is the outermost one — short-circuiting here also skips
        the inner guards, which is what we want for a call that never ran.
        """
        key = self._budget_key(request)
        if self._turns_used(key) < self.turn_limit:
            return None
        tool_call = request.tool_call or {}
        name = tool_call.get("name")
        if name in _POST_BUDGET_ALLOWED_TOOLS:
            return None
        logger.warning(
            "[linsight-turn-budget] graph={} key={} budget spent ({}/{}) — refusing tool call '{}'",
            "sub" if self.is_subagent else "main",
            key or "-",
            self._turns_used(key),
            self.turn_limit,
            name,
        )
        # Deliberately NOT status="error". An error ToolMessage feeds the L3
        # tool-loop breaker's consecutive-failure counter, and enough refusals in a
        # row would abort the run into the apology path — the very outcome this
        # ladder exists to prevent. A plain result also ends any failure streak the
        # breaker was tracking, which is correct: nothing failed here.
        return ToolMessage(
            content=_BUDGET_SPENT_TOOL_REPLY.format(tool_name=name),
            tool_call_id=tool_call.get("id", ""),
            name=name,
        )

    async def awrap_tool_call(self, request, handler):
        blocked = self._budget_blocked_reply(request)
        if blocked is not None:
            return blocked
        return await handler(request)

    def wrap_tool_call(self, request, handler):
        blocked = self._budget_blocked_reply(request)
        if blocked is not None:
            return blocked
        return handler(request)

    def _mark_soft_landing(self) -> None:
        """Flag the run as wrapped-up-early for the task executor's user-facing note.

        Deliberately sticky: a turn that triggered a wrap-up nudge and was then
        refunded (``_refund_turn``) does NOT clear this. The nudge really was sent and
        really did shape that turn, so telling the user their result was closed out
        early is still true.
        """
        if self._budget_sink is not None:
            self._budget_sink["soft_landing"] = True

    def _degrade_or_raise(self, exc: Exception) -> AIMessage:
        # Main graph: a no-tool-call synthetic message would just end the main
        # loop mid-reasoning; re-raise for a clean, classified task-level failure.
        if not self.is_subagent:
            raise exc
        self._degrade_count += 1
        if self._degrade_count > self.max_degrade:
            logger.warning(
                "[linsight-resilience] subagent degrade budget exhausted "
                f"({self._degrade_count}/{self.max_degrade}); failing the step: "
                f"{type(exc).__name__}: {exc}"
            )
            raise exc
        logger.warning(
            "[linsight-resilience] subagent model call degraded "
            f"({self._degrade_count}/{self.max_degrade}): {type(exc).__name__}: {exc}"
        )
        return AIMessage(content=_DEGRADE_MESSAGE)

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse | AIMessage:
        # exc_attempts (transient failures) and trunc_attempts (L2 truncation) use
        # SEPARATE budgets so a truncation retry never eats the exception-retry
        # budget and vice-versa. ``current`` carries the (possibly nudged) request.
        # The turn budget is applied ONCE, outside the retry loop.
        current, budget_key = self._apply_turn_budget(request)
        exc_attempts = 0
        trunc_attempts = 0
        incomplete_attempts = 0
        while True:
            try:
                response = await handler(current)
            except Exception as exc:
                behavior = classify_behavior(exc)
                if behavior is Behavior.FAIL_FAST:
                    logger.warning(f"[linsight-resilience] fail-fast ({type(exc).__name__}): {exc}")
                    raise
                if behavior is Behavior.RETRYABLE and exc_attempts < self.max_retries:
                    delay = self._delay(exc_attempts)
                    logger.warning(
                        f"[linsight-resilience] retryable {type(exc).__name__} "
                        f"(attempt {exc_attempts + 1}/{self.max_retries + 1}); sleeping {delay:.1f}s"
                    )
                    exc_attempts += 1
                    if delay > 0:
                        await asyncio.sleep(delay)
                    continue
                # DEGRADABLE, or RETRYABLE with retries exhausted.
                return self._degrade_or_raise(exc)
            # One greppable diagnostic line per model call (finish_reason / tokens /
            # tool-call arg keys) — the only observability for task-mode calls.
            _log_call_diagnostics(response, is_subagent=self.is_subagent)
            # L2 truncation guard: a length-truncated tool call → nudge + retry.
            if trunc_attempts < self.truncation_retry_limit and _is_truncated_tool_call(response):
                trunc_attempts += 1
                logger.warning(
                    f"[linsight-resilience] truncated tool call (finish_reason=length); "
                    f"nudging to write in smaller parts (retry {trunc_attempts}/{self.truncation_retry_limit})"
                )
                current = _with_truncation_nudge(current)
                continue
            # Incomplete-stream guard: a stream closed mid-turn yields a tool-call-less
            # AIMessage that the graph reads as a clean finish. Re-send the call; only
            # when it keeps coming back incomplete do we fail (main graph) / degrade
            # (subagent) — the run is never allowed to silently pass off a cut-off
            # narration as its answer.
            if _is_incomplete_stream_response(response):
                if incomplete_attempts < _INCOMPLETE_STREAM_RETRY_LIMIT:
                    delay = self._delay(incomplete_attempts)
                    logger.warning(
                        "[linsight-resilience] incomplete stream response "
                        "(no finish_reason, no usage, no tool call) "
                        "(attempt {}/{}); sleeping {:.1f}s",
                        incomplete_attempts + 1,
                        _INCOMPLETE_STREAM_RETRY_LIMIT,
                        delay,
                    )
                    incomplete_attempts += 1
                    if delay > 0:
                        await asyncio.sleep(delay)
                    continue
                return self._degrade_or_raise(
                    IncompleteStreamError(
                        f"provider closed the response stream before the turn finished "
                        f"({_INCOMPLETE_STREAM_RETRY_LIMIT + 1} attempts)"
                    )
                )
            # Two-phase turn accounting: the soft-landing STAGE had to be picked before
            # the call (it shapes the request), but whether this turn did any real work
            # is only knowable from the response. Refund here — the loop's SINGLE
            # success exit — so a transient retry or a truncation nudge (both
            # ``continue`` above) can never double-refund, and a degraded call (which
            # returns from the except branch) is never refunded: it really did burn
            # model calls.
            if _is_state_only_turn(response):
                self._refund_turn(budget_key)
            return response

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse | AIMessage:
        current, budget_key = self._apply_turn_budget(request)
        exc_attempts = 0
        trunc_attempts = 0
        incomplete_attempts = 0
        while True:
            try:
                response = handler(current)
            except Exception as exc:
                behavior = classify_behavior(exc)
                if behavior is Behavior.FAIL_FAST:
                    raise
                if behavior is Behavior.RETRYABLE and exc_attempts < self.max_retries:
                    delay = self._delay(exc_attempts)
                    exc_attempts += 1
                    if delay > 0:
                        time.sleep(delay)
                    continue
                return self._degrade_or_raise(exc)
            _log_call_diagnostics(response, is_subagent=self.is_subagent)
            if trunc_attempts < self.truncation_retry_limit and _is_truncated_tool_call(response):
                trunc_attempts += 1
                current = _with_truncation_nudge(current)
                continue
            # Incomplete-stream guard — see the async twin above.
            if _is_incomplete_stream_response(response):
                if incomplete_attempts < _INCOMPLETE_STREAM_RETRY_LIMIT:
                    delay = self._delay(incomplete_attempts)
                    incomplete_attempts += 1
                    if delay > 0:
                        time.sleep(delay)
                    continue
                return self._degrade_or_raise(
                    IncompleteStreamError(
                        f"provider closed the response stream before the turn finished "
                        f"({_INCOMPLETE_STREAM_RETRY_LIMIT + 1} attempts)"
                    )
                )
            # Refund a pure state-maintenance turn — see the async twin above for why
            # this sits at the loop's single success exit.
            if _is_state_only_turn(response):
                self._refund_turn(budget_key)
            return response


def build_resilience_middleware(
    linsight_conf, *, is_subagent: bool, budget_sink: dict | None = None
) -> LinsightModelResilienceMiddleware:
    """Construct a middleware instance from ``LinsightConf`` (one per graph).

    ``budget_sink`` is the task executor's shared dict; only the main graph passes
    one, so a subagent wrapping up early never adds a note to the user's result.
    """
    turn_limit = (
        getattr(linsight_conf, "max_model_turns_subagent", 30)
        if is_subagent
        else getattr(linsight_conf, "max_model_turns", 115)
    )
    return LinsightModelResilienceMiddleware(
        max_retries=getattr(linsight_conf, "retry_num", 3),
        initial_delay=float(getattr(linsight_conf, "retry_sleep", 5)),
        max_degrade=getattr(linsight_conf, "max_degrade", 3),
        truncation_retry_limit=getattr(linsight_conf, "truncation_retry_limit", 2),
        is_subagent=is_subagent,
        turn_limit=turn_limit,
        soft_landing_turns=getattr(linsight_conf, "soft_landing_turns", 8),
        budget_sink=budget_sink,
    )
