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
from collections.abc import Callable, Iterator, Sequence
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
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
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

_SUMMARY_ERROR_PREFIX = "Error generating summary"
_SUMMARY_ATTEMPTS = 2

# The per-task builder the harness-profile factory reads. Set around the
# synchronous ``create_deep_agent`` assembly, so concurrent asyncio tasks never
# see each other's value.
_SUMMARIZER_BUILDER: contextvars.ContextVar[Callable[[], AgentMiddleware] | None] = contextvars.ContextVar(
    "bisheng_linsight_summarizer_builder", default=None
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

    def _count_tokens(self, messages, system_message, tools) -> int:
        if self._usable_input is None:
            return super()._count_tokens(messages, system_message, tools)
        counted = [system_message, *messages] if system_message is not None else list(messages)
        return count_context_tokens(counted, tools)

    def _check_summary(self, summary: str, attempt: int) -> bool:
        if not summary.startswith(_SUMMARY_ERROR_PREFIX):
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


def _summarizer_factory() -> list[AgentMiddleware]:
    build = _SUMMARIZER_BUILDER.get()
    if build is None:
        # Only reachable if something other than create_linsight_agent builds a
        # deep agent for a provider registered here; fail loudly rather than
        # silently assembling an agent without any summarization.
        raise RuntimeError("deep agent assembled outside bisheng_summarization(); no summarizer configured")
    return [build()]


def _ensure_profile(provider: str) -> None:
    if provider in _REGISTERED_PROVIDERS:
        return
    register_harness_profile(
        provider,
        HarnessProfile(
            excluded_middleware=frozenset({"SummarizationMiddleware"}), extra_middleware=_summarizer_factory
        ),
    )
    _REGISTERED_PROVIDERS.add(provider)


@contextlib.contextmanager
def bisheng_summarization(model: BaseChatModel, backend: Any, usable_input: int | None) -> Iterator[None]:
    """Make ``create_deep_agent`` inside this block use BishengSummarizationMiddleware.

    Registers (once per provider) a harness profile that drops the framework's
    summarization middleware and adds ours through a factory; the factory builds
    one instance per graph (main and each subagent) with this task's budget.
    A model whose provider cannot be determined keeps the framework middleware.
    """
    provider = get_model_provider(model)
    if not provider:
        yield
        return
    _ensure_profile(provider)
    token = _SUMMARIZER_BUILDER.set(lambda: BishengSummarizationMiddleware(model, backend, usable_input))
    try:
        yield
    finally:
        _SUMMARIZER_BUILDER.reset(token)


# ---------------------------------------------------------------------------
# Per-result budget (spec AC-19, AC-20)
# ---------------------------------------------------------------------------

# Share of the usable input one tool result may take: equal to what compression
# keeps verbatim, so a fresh result is never folded into the summary at once.
RESULT_SHARE = 0.10

_READ_FILE = "read_file"
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
        if not isinstance(result, ToolMessage) or not isinstance(result.content, str):
            return result
        if estimate_text_tokens(result.content) <= self._limit_tokens:
            return result
        file_path = ((request.tool_call or {}).get("args") or {}).get("file_path", "")
        hint = _READ_TRUNCATION_HINT.format(file_path=file_path)
        clipped = _clip_to_tokens(result.content, max(1, self._limit_tokens - estimate_text_tokens(hint)))
        return result.model_copy(update={"content": clipped + hint})

    def wrap_tool_call(self, request, handler):
        result = handler(request)
        name = (request.tool_call or {}).get("name")
        if name == _READ_FILE:
            return self._clip_read(request, result)
        if name in TOOLS_EXCLUDED_FROM_EVICTION:
            return result
        return self._evictor._intercept_large_tool_result(result, request.runtime)

    async def awrap_tool_call(self, request, handler):
        result = await handler(request)
        name = (request.tool_call or {}).get("name")
        if name == _READ_FILE:
            return self._clip_read(request, result)
        if name in TOOLS_EXCLUDED_FROM_EVICTION:
            return result
        return await self._evictor._aintercept_large_tool_result(result, request.runtime)
