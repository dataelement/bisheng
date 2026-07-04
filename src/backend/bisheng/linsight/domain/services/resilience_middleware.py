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
from collections.abc import Awaitable, Callable

from langchain.agents.middleware._retry import calculate_delay
from langchain.agents.middleware.types import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage
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


def _with_truncation_nudge(request: ModelRequest) -> ModelRequest:
    """A new request with the corrective nudge appended (ephemeral — retry only)."""
    return request.override(messages=[*request.messages, HumanMessage(content=_TRUNCATION_NUDGE)])


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
        self._degrade_count = 0

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
        current = request
        exc_attempts = 0
        trunc_attempts = 0
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
            # L2 truncation guard: a length-truncated tool call → nudge + retry.
            if trunc_attempts < self.truncation_retry_limit and _is_truncated_tool_call(response):
                trunc_attempts += 1
                logger.warning(
                    f"[linsight-resilience] truncated tool call (finish_reason=length); "
                    f"nudging to write in smaller parts (retry {trunc_attempts}/{self.truncation_retry_limit})"
                )
                current = _with_truncation_nudge(current)
                continue
            return response

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse | AIMessage:
        current = request
        exc_attempts = 0
        trunc_attempts = 0
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
            if trunc_attempts < self.truncation_retry_limit and _is_truncated_tool_call(response):
                trunc_attempts += 1
                current = _with_truncation_nudge(current)
                continue
            return response


def build_resilience_middleware(linsight_conf, *, is_subagent: bool) -> LinsightModelResilienceMiddleware:
    """Construct a middleware instance from ``LinsightConf`` (one per graph)."""
    return LinsightModelResilienceMiddleware(
        max_retries=getattr(linsight_conf, "retry_num", 3),
        initial_delay=float(getattr(linsight_conf, "retry_sleep", 5)),
        max_degrade=getattr(linsight_conf, "max_degrade", 3),
        truncation_retry_limit=getattr(linsight_conf, "truncation_retry_limit", 2),
        is_subagent=is_subagent,
    )
