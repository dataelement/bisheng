"""Recognise a provider's "request exceeds the context window" error (F087).

deepagents compresses history and retries only when the model raises
``ContextOverflowError``. langchain-openai recognises just OpenAI's own wording, so
a vLLM / DeepSeek / SGLang / llama.cpp rejection would otherwise surface as a plain
``BadRequestError`` and fail the task outright.

The re-raised error keeps the original SDK type and its ``body`` / ``status_code``:
``BishengLLM`` is shared by daily chat, assistants and workflows, and code there
catches SDK error types or reads the provider message from ``exc.body``
(design.md decision 5).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from langchain_core.exceptions import ContextOverflowError

from bisheng.llm.domain.llm.exceptions import LLMContextOverflowError


@dataclass(frozen=True)
class _Rule:
    source: str
    marker: str


# Matched case-insensitively against the error text. Each rule has a test using
# the provider's real wording (test/llm/test_bisheng_llm_context_overflow.py).
RULES: tuple[_Rule, ...] = (
    _Rule("vllm-legacy / deepseek", "maximum context length is"),
    _Rule("vllm", "is longer than the maximum model length"),
    _Rule("openai", "context_length_exceeded"),
    _Rule("anthropic", "prompt is too long"),
    _Rule("sglang", "exceeds the maximum allowed length"),
    _Rule("llama.cpp", "exceeds the available context size"),
)

# Pull the provider-reported input size out of the message, when it states one.
_INPUT_TOKEN_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"prompt contains at least (\d+) input tokens", re.IGNORECASE),
    re.compile(r"parameter=input_tokens, value=(\d+)", re.IGNORECASE),
    re.compile(r"you requested (\d+) tokens \((\d+) in the messages", re.IGNORECASE),
    re.compile(r"decoder prompt \(length (\d+)\)", re.IGNORECASE),
    re.compile(r"input length \((\d+) tokens?\)", re.IGNORECASE),
    re.compile(r"prompt is too long: (\d+) tokens", re.IGNORECASE),
    re.compile(r"request \((\d+) tokens\) exceeds the available context size", re.IGNORECASE),
)


def _error_text(exc: BaseException) -> str:
    parts = [str(exc), str(getattr(exc, "message", "") or "")]
    body = getattr(exc, "body", None)
    if body is not None:
        try:
            parts.append(json.dumps(body, ensure_ascii=False))
        except (TypeError, ValueError):
            parts.append(str(body))
    return "\n".join(parts)


def matches_context_overflow(text: str) -> bool:
    lowered = text.lower()
    return any(rule.marker.lower() in lowered for rule in RULES)


def extract_input_tokens(text: str) -> int | None:
    for pattern in _INPUT_TOKEN_PATTERNS:
        match = pattern.search(text)
        if match:
            # "you requested N tokens (M in the messages ...)" — M is the input.
            return int(match.group(match.lastindex or 1))
    return None


def _rebuild(exc: BaseException, text: str) -> ContextOverflowError:
    import openai

    message = getattr(exc, "message", None) or str(exc)
    if isinstance(exc, openai.APIStatusError):
        from langchain_openai.chat_models.base import OpenAIContextOverflowError

        return OpenAIContextOverflowError(message=message, response=exc.response, body=exc.body)
    try:
        import anthropic
    except ImportError:  # anthropic is an optional provider SDK
        anthropic = None
    if anthropic is not None and isinstance(exc, anthropic.APIStatusError):
        from langchain_anthropic.chat_models import AnthropicContextOverflowError

        return AnthropicContextOverflowError(message=message, response=exc.response, body=exc.body)
    return LLMContextOverflowError(
        message,
        body=getattr(exc, "body", None),
        status_code=getattr(exc, "status_code", None),
    )


def as_context_overflow(exc: BaseException) -> ContextOverflowError | None:
    """The context-overflow form of ``exc``, or ``None`` when it is something else.

    An error that already is a ``ContextOverflowError`` is returned as-is (with
    ``reported_input_tokens`` filled in) so the caller can re-raise it unchanged.
    """
    text = _error_text(exc)
    if isinstance(exc, ContextOverflowError):
        overflow = exc
    elif matches_context_overflow(text):
        overflow = _rebuild(exc, text)
    else:
        return None
    if getattr(overflow, "reported_input_tokens", None) is None:
        overflow.reported_input_tokens = extract_input_tokens(text)
    return overflow
