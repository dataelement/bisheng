"""LLM question rewriting for the portal hot-search pipeline (F048)."""

from __future__ import annotations

import re
from collections.abc import Callable

from bisheng.knowledge.domain.services.portal_hot_search_text_utils import count_han

LLMInvoke = Callable[[str], str]

_QUESTION_WORDS = (
    "如何",
    "怎么",
    "怎样",
    "什么",
    "是否",
    "哪些",
    "哪个",
    "为何",
    "为什么",
    "多少",
    "能否",
    "可否",
)

REWRITE_PROMPT = """请将搜索主题改写成一个完整的中文问句。
必须保留原来的关键对象和问题意图。
不得增加时间、人物、制度名称和事实结论。
长度控制在12至30个汉字。
只返回一个问句。

搜索主题：{query}"""

_MIN_HAN = 12
_MAX_HAN = 30


def is_complete_question(text: str) -> bool:
    """Whether text already reads as a complete 12-30 han Chinese question."""
    if not text:
        return False
    stripped = text.strip()
    if not stripped.endswith(("？", "?")):
        return False
    han = count_han(stripped)
    if han < _MIN_HAN or han > _MAX_HAN:
        return False
    return any(word in stripped for word in _QUESTION_WORDS)


def _sanitize_llm_question(text: str) -> str | None:
    """Extract a single clean question from an LLM response, or None if invalid."""
    if not text:
        return None
    candidate = text.strip().strip('"').strip("“”").strip()
    # Drop any leading enumeration like "1. " or "- ".
    candidate = re.sub(r"^\s*[-\d.、)\s]+", "", candidate).strip()
    # Keep only the first line / first question segment.
    candidate = candidate.splitlines()[0].strip() if candidate else candidate
    if not candidate:
        return None
    if not candidate.endswith(("？", "?")):
        candidate = candidate + "？"
    han = count_han(candidate)
    if han < _MIN_HAN or han > _MAX_HAN:
        return None
    return candidate


class PortalHotSearchRewriteService:
    """Turns an intent's canonical query into a standard question.

    ``llm_invoke`` maps a prompt to the model's raw text response, letting the
    pipeline inject the real LLM while tests pass a stub.
    """

    def __init__(self, llm_invoke: LLMInvoke | None = None) -> None:
        self._llm_invoke = llm_invoke

    def rewrite(self, canonical_query: str) -> tuple[str, str]:
        """Return (display_query, rewrite_source).

        rewrite_source is one of ``passthrough`` / ``llm`` / ``fallback``.
        """
        canonical_query = (canonical_query or "").strip()
        if is_complete_question(canonical_query):
            return canonical_query, "passthrough"
        if self._llm_invoke is not None:
            try:
                response = self._llm_invoke(REWRITE_PROMPT.format(query=canonical_query))
                sanitized = _sanitize_llm_question(response)
                if sanitized is not None:
                    return sanitized, "llm"
            except Exception:
                pass
        return f"{canonical_query}？", "fallback"
