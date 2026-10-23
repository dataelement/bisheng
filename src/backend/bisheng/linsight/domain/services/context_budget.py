"""Task-mode context budgeting on top of deepagents (F087 P1).

Token counting (design.md decision 10): deepagents estimates four characters per
token, which undercounts Chinese by half or more. Here a CJK character counts as
one token, and the full-context count starts from the provider-reported total of
the latest model reply, so only the messages after it are estimated.
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import math
from collections.abc import Iterator, Sequence
from typing import Any

from deepagents import HarnessProfile, register_harness_profile
from deepagents._models import get_model_provider
from deepagents.middleware.filesystem import (
    TOOLS_EXCLUDED_FROM_EVICTION,
    FilesystemMiddleware,
    _extract_text_from_message,
)
from deepagents.middleware.summarization import SummarizationMiddleware, compute_summarization_defaults
from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage, get_buffer_string, trim_messages
from langchain_core.messages.utils import count_tokens_approximately
from loguru import logger

from bisheng.common.errcode.linsight import LinsightContextCompressFailedError

# Roughly what langchain's approximate counter adds per message for role/framing.
_PER_MESSAGE_OVERHEAD = 3
_CHARS_PER_TOKEN = 4

# CJK Unified Ideographs (+ Extension A), compatibility ideographs, Hiragana,
# Katakana, Hangul syllables, CJK symbols/punctuation and full-width forms.
_CJK_RANGES = (
    (0x3000, 0x303F),
    (0x3040, 0x30FF),
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xAC00, 0xD7AF),
    (0xF900, 0xFAFF),
    (0xFF00, 0xFFEF),
)


def _is_cjk(char: str) -> bool:
    code = ord(char)
    return any(low <= code <= high for low, high in _CJK_RANGES)


def estimate_text_tokens(text: str) -> int:
    cjk = sum(1 for char in text if _is_cjk(char))
    other = len(text) - cjk
    return cjk + math.ceil(other / _CHARS_PER_TOKEN)


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "\n".join(parts)
    return ""


def _message_text(message: BaseMessage) -> str:
    text = _content_text(message.content)
    if isinstance(message, AIMessage) and message.tool_calls:
        text += json.dumps([call.get("args", {}) for call in message.tool_calls], ensure_ascii=False)
    return text


def estimate_tokens(messages: Sequence[BaseMessage], tools: Sequence[Any] | None = None) -> int:
    """CJK-aware estimate for a list of messages (and, optionally, tool schemas)."""
    total = sum(estimate_text_tokens(_message_text(message)) + _PER_MESSAGE_OVERHEAD for message in messages)
    if tools:
        total += estimate_text_tokens(
            json.dumps([_tool_schema(tool) for tool in tools], ensure_ascii=False, default=str)
        )
    return total


def _tool_schema(tool: Any) -> Any:
    if isinstance(tool, dict):
        return tool
    return {"name": getattr(tool, "name", ""), "description": getattr(tool, "description", "")}


def _reported_total(message: BaseMessage) -> int | None:
    if not isinstance(message, AIMessage) or not message.usage_metadata:
        return None
    total = message.usage_metadata.get("total_tokens")
    return total if isinstance(total, int) and total > 0 else None


def count_context_tokens(messages: Sequence[BaseMessage], tools: Sequence[Any] | None = None) -> int:
    """Tokens the next request will carry.

    The latest reply with provider usage reports input + output of its own call,
    which is exactly the context up to and including that reply; only later
    messages (typically fresh tool results) are estimated. A reply without usage
    (a degraded synthetic message, a provider that omits usage) is skipped in
    favour of an earlier one. Without any usage, everything is estimated.
    """
    for index in range(len(messages) - 1, -1, -1):
        base = _reported_total(messages[index])
        if base is not None:
            return base + estimate_tokens(messages[index + 1 :])
    return estimate_tokens(messages, tools)


# ---------------------------------------------------------------------------
# BiSheng summarization middleware (design.md decision 7)
# ---------------------------------------------------------------------------

# What langchain returns instead of raising when the summary call fails, or when
# trimming left nothing to summarise. Neither is a summary.
_SUMMARY_FAILURE_PREFIXES = ("Error generating summary", "Previous conversation was too long to summarize")
_SUMMARY_ATTEMPTS = 2

# Set around the synchronous ``create_deep_agent`` assembly; per asyncio task.
_SUMMARIZER_ACTIVE: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "bisheng_linsight_summarizer_active", default=False
)
_REGISTERED_PROVIDERS: set[str] = set()


class BishengSummarizationMiddleware(SummarizationMiddleware):
    """deepagents' summarization with task-mode budgets.

    With a known usable input: compress at 85%, keep 10%, hand the summary call
    at most half of the usable input, and count the full context from the
    provider-reported usage (``count_context_tokens``). With an unknown window:
    exactly the framework defaults (spec AC-08). In both modes a failed summary
    is retried once and then fails the task instead of replacing the history
    with an error string (spec AC-17, AC-18).

    Its ``name`` is the class name, not the framework's public alias, so the
    harness-profile exclusion of ``SummarizationMiddleware`` leaves it in place.
    """

    def __init__(self, model: BaseChatModel, backend: Any, usable_input: int | None):
        if usable_input is None:
            defaults = compute_summarization_defaults(model)
            super().__init__(
                model=model,
                backend=backend,
                trigger=defaults["trigger"],
                keep=defaults["keep"],
                token_counter=count_tokens_approximately,
                trim_tokens_to_summarize=None,
                truncate_args_settings=defaults["truncate_args_settings"],
            )
        else:
            super().__init__(
                model=model,
                backend=backend,
                trigger=("fraction", 0.85),
                keep=("fraction", 0.10),
                # Partial counts (keep cut-off, trimming) must be a pure estimate:
                # a usage base only describes the whole context.
                token_counter=estimate_tokens,
                trim_tokens_to_summarize=max(1, usable_input // 2),
                truncate_args_settings={"trigger": ("fraction", 0.85), "keep": ("fraction", 0.10)},
            )
        self._usable_input = usable_input
        if usable_input is not None:
            # langchain trims with start_on="human"; a task-mode history has a
            # human message only at its head, so the trimmed tail came back empty
            # and every compression replaced the history with a canned sentence.
            self._lc_helper._trim_messages_for_summary = self._trim_for_summary

    def _trim_for_summary(self, messages: list) -> list:
        """Fit the summary input into half the usable input, keeping its newest part.

        Keeps the leading human message (the task instruction, or the previous
        summary) when it fits in half the budget, then the newest messages that
        fit, starting at an AI or human message so no tool result is orphaned.
        If even the newest step alone is too big, its text is clipped into one
        message so the summary model still sees the latest work.
        """
        budget = self._lc_helper.trim_tokens_to_summarize
        if not messages or estimate_tokens(messages) <= budget:
            return messages
        head = messages[:1] if isinstance(messages[0], HumanMessage) else []
        if head and estimate_tokens(head) > budget // 2:
            head = []
        rest = messages[len(head) :]
        remaining = max(1, budget - estimate_tokens(head))
        try:
            tail = trim_messages(
                rest,
                max_tokens=remaining,
                token_counter=estimate_tokens,
                strategy="last",
                start_on=("human", "ai"),
                allow_partial=False,
            )
        except Exception:
            # Same spirit as langchain's own fallback, but within budget: an
            # unexpected message shape falls back to the clipped-text path below.
            logger.opt(exception=True).warning("[linsight-context-window] trim_messages failed; clipping text")
            tail = []
        if not tail:
            text = get_buffer_string(rest)
            tail = [HumanMessage(content=_clip_suffix_to_tokens(text, remaining))]
        return [*head, *tail]

    def _count_tokens(self, messages, system_message, tools) -> int:
        if self._usable_input is None:
            return super()._count_tokens(messages, system_message, tools)
        counted = [system_message, *messages] if system_message is not None else list(messages)
        return count_context_tokens(counted, tools)

    def _check_summary(self, summary: str, attempt: int) -> bool:
        if not summary.startswith(_SUMMARY_FAILURE_PREFIXES):
            return True
        logger.error(
            "[linsight-context-window] summary generation failed (attempt {}/{}): {}",
            attempt,
            _SUMMARY_ATTEMPTS,
            summary,
        )
        return False

    def _create_summary(self, messages_to_summarize: list) -> str:
        for attempt in range(1, _SUMMARY_ATTEMPTS + 1):
            summary = super()._create_summary(messages_to_summarize)
            if self._check_summary(summary, attempt):
                return summary
        raise LinsightContextCompressFailedError(msg=summary)

    async def _acreate_summary(self, messages_to_summarize: list) -> str:
        for attempt in range(1, _SUMMARY_ATTEMPTS + 1):
            summary = await super()._acreate_summary(messages_to_summarize)
            if self._check_summary(summary, attempt):
                return summary
        raise LinsightContextCompressFailedError(msg=summary)


def _summarizer_guard() -> list[AgentMiddleware]:
    """harness-profile ``extra_middleware`` factory: adds nothing, only checks.

    The profile drops the framework's summarization for this provider in every
    process-wide build; ours is passed in ``middleware=`` by create_linsight_agent.
    A build outside ``bisheng_summarization()`` would silently run with no
    summarization at all, so it fails loudly instead.
    """
    if not _SUMMARIZER_ACTIVE.get():
        raise RuntimeError("deep agent assembled outside bisheng_summarization(); no summarizer configured")
    return []


def _ensure_profile(provider: str) -> None:
    if provider in _REGISTERED_PROVIDERS:
        return
    register_harness_profile(
        provider,
        HarnessProfile(excluded_middleware=frozenset({"SummarizationMiddleware"}), extra_middleware=_summarizer_guard),
    )
    _REGISTERED_PROVIDERS.add(provider)


@contextlib.contextmanager
def bisheng_summarization(model: BaseChatModel) -> Iterator[bool]:
    """Drop deepagents' summarization from every graph ``create_deep_agent`` builds here.

    Registers (once per provider) a harness profile excluding the framework's
    ``SummarizationMiddleware``. Yields whether it applies: the caller must then
    put a ``BishengSummarizationMiddleware`` FIRST in the main ``middleware=`` list
    and in each subagent's list, so it wraps the resilience middleware as the
    framework's did (a retry inside resilience must not re-run compression).
    A model whose provider cannot be determined keeps the framework middleware
    (yields False).
    """
    provider = get_model_provider(model)
    if not provider:
        yield False
        return
    _ensure_profile(provider)
    token = _SUMMARIZER_ACTIVE.set(True)
    try:
        yield True
    finally:
        _SUMMARIZER_ACTIVE.reset(token)


# ---------------------------------------------------------------------------
# Per-result budget (spec AC-19, AC-20)
# ---------------------------------------------------------------------------

# Share of the usable input one tool result may take: equal to what compression
# keeps verbatim, so a fresh result is never folded into the summary at once.
RESULT_SHARE = 0.10

_READ_FILE = "read_file"
# Self-truncating listing/search tools: offloading their output would only invite
# another listing, so they are clipped with a "narrow it down" hint instead.
_SEARCH_TOOLS = ("ls", "glob", "grep")
_SEARCH_TRUNCATION_HINT = (
    "\n\n[结果超过本模型单次可读的长度，已截断。请缩小路径范围或改用更具体的匹配条件后重试。]"
    "\n[Output truncated: it exceeds what this model can read at once. Narrow the path or pattern.]"
)
_READ_TRUNCATION_HINT = (
    "\n\n[输出超过本模型单次可读的长度，已截断。请用 read_file 的 offset / limit 参数分页继续读取 {file_path}。]"
    "\n[Output truncated: it exceeds what this model can read at once. Page through {file_path} "
    "with read_file offset / limit.]"
)


class _ResultEvictor(FilesystemMiddleware):
    """Never placed in a middleware stack: borrows the framework's offload writing
    (backend resolution, ``/large_tool_results/`` naming, preview, ``Command``
    handling) and only swaps the size test for a CJK-aware token count."""

    def __init__(self, backend: Any, limit_tokens: int):
        # Any positive limit enables eviction in the base class; the real test
        # happens in the overrides below.
        super().__init__(backend=backend, tool_token_limit_before_evict=1)
        self._limit_tokens = limit_tokens

    def _within_budget(self, message) -> bool:
        return estimate_text_tokens(_extract_text_from_message(message)) <= self._limit_tokens

    def _process_large_message(self, message, resolved_backend):
        if self._within_budget(message):
            return message, False
        return super()._process_large_message(message, resolved_backend)

    async def _aprocess_large_message(self, message, resolved_backend):
        if self._within_budget(message):
            return message, False
        return await super()._aprocess_large_message(message, resolved_backend)


def _clip_suffix_to_tokens(text: str, limit_tokens: int) -> str:
    """Longest suffix of ``text`` whose CJK-aware estimate fits ``limit_tokens``."""
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if estimate_text_tokens(text[len(text) - middle :]) <= limit_tokens:
            low = middle
        else:
            high = middle - 1
    return text[len(text) - low :]


def _clip_to_tokens(text: str, limit_tokens: int) -> str:
    """Longest prefix of ``text`` whose CJK-aware estimate fits ``limit_tokens``."""
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if estimate_text_tokens(text[:middle]) <= limit_tokens:
            low = middle
        else:
            high = middle - 1
    return text[:low]


class ToolResultBudgetMiddleware(AgentMiddleware):
    """Cap one tool result at 10% of the usable input (F087 design decision 7, AC-19/20).

    Sits INSIDE the framework's FilesystemMiddleware (BiSheng middleware is
    appended after it), so it sees each result first: an oversized result is
    offloaded to ``/large_tool_results/<tool_call_id>`` with a preview, an
    oversized ``read_file`` page is clipped with a pagination hint (offloading a
    read would only invite reading it again). The framework's own 80000-character
    threshold never fires on what is left. Only mounted when the window is known.
    """

    def __init__(self, backend: Any, usable_input: int):
        super().__init__()
        self._limit_tokens = max(1, int(usable_input * RESULT_SHARE))
        self._evictor = _ResultEvictor(backend, self._limit_tokens)

    def _clip_read(self, request, result):
        file_path = ((request.tool_call or {}).get("args") or {}).get("file_path", "")
        return self._clip(result, _READ_TRUNCATION_HINT.format(file_path=file_path))

    def _clip(self, result, hint: str):
        if not isinstance(result, ToolMessage) or not isinstance(result.content, str):
            return result
        if estimate_text_tokens(result.content) <= self._limit_tokens:
            return result
        clipped = _clip_to_tokens(result.content, max(1, self._limit_tokens - estimate_text_tokens(hint)))
        return result.model_copy(update={"content": clipped + hint})

    def wrap_tool_call(self, request, handler):
        result = handler(request)
        name = (request.tool_call or {}).get("name")
        if name == _READ_FILE:
            return self._clip_read(request, result)
        if name in _SEARCH_TOOLS:
            return self._clip(result, _SEARCH_TRUNCATION_HINT)
        if name in TOOLS_EXCLUDED_FROM_EVICTION:
            return result
        return self._evictor._intercept_large_tool_result(result, request.runtime)

    async def awrap_tool_call(self, request, handler):
        result = await handler(request)
        name = (request.tool_call or {}).get("name")
        if name == _READ_FILE:
            return self._clip_read(request, result)
        if name in _SEARCH_TOOLS:
            return self._clip(result, _SEARCH_TRUNCATION_HINT)
        if name in TOOLS_EXCLUDED_FROM_EVICTION:
            return result
        return await self._evictor._aintercept_large_tool_result(result, request.runtime)
