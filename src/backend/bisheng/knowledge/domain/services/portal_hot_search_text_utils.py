"""Text cleaning helpers for the portal hot-search pipeline (F048)."""

from __future__ import annotations

import re
import unicodedata

_WHITESPACE_RE = re.compile(r"\s+")
_HAN_RE = re.compile(r"[\u4e00-\u9fff]")
_ALNUM_HAN_RE = re.compile(r"[\u4e00-\u9fffA-Za-z]")
# Trailing sentence punctuation (both half/full width) to strip.
_TRAILING_PUNCT = "。.!！?？;；,，、~～ "


def count_han(text: str) -> int:
    """Return the number of CJK ideographs in ``text``."""
    return len(_HAN_RE.findall(text or ""))


def has_letter_or_han(text: str) -> bool:
    """Whether ``text`` contains at least one letter or CJK ideograph."""
    return bool(_ALNUM_HAN_RE.search(text or ""))


def normalize_hot_search_query(raw: str) -> str:
    """Clean a raw search query for dedup and grouping.

    Steps: NFKC full/half-width unification, whitespace collapse, trailing
    sentence-punctuation removal, lowercase + casefold.
    """
    if not raw:
        return ""
    # NFKC unifies full-width chars/digits/letters to their half-width forms.
    text = unicodedata.normalize("NFKC", raw)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    text = text.rstrip(_TRAILING_PUNCT)
    return text.casefold().strip()
