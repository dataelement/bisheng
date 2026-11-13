"""Deterministic validation of memory content (design decision 14, §4.1 end).

Every write path (explicit tool, consolidation, manual add/edit) runs
``validate_item`` before anything is stored. Each rejection raises a distinct
121xx error code so the model or the UI can tell the user why.
"""

from __future__ import annotations

import math
import re

from bisheng.common.errcode.memory import (
    MemoryContentEmptyError,
    MemoryContentRelativeTimeError,
    MemoryContentSensitiveError,
    MemoryContentTooLongError,
    MemoryContentTypeInvalidError,
)
from bisheng.memory.domain.models.memory_item import ITEM_TYPES

MAX_CONTENT_CHARS = 200

_KEY_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\b(?:sk|pk|rk)_(?:live|test)_[A-Za-z0-9]{16,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bBearer\s+[A-Za-z0-9_\-\.=]{16,}", re.IGNORECASE),
]

_PASSWORD_ASSIGNMENT = re.compile(
    r"(?:密码|口令|密钥|秘钥|令牌|password|passwd|pwd|passcode|api[_ ]?key|secret|token)"
    r"\s*(?:是|为|=|:|：|is)\s*\S+",
    re.IGNORECASE,
)

_TOKEN_CANDIDATE = re.compile(r"[A-Za-z0-9+/_=\-]{24,}")
_ID_CARD = re.compile(r"(?<!\d)(\d{17}[\dXx])(?!\d)")
_CARD_CANDIDATE = re.compile(r"(?<![\d])(\d(?:[ \-]?\d){12,18})(?![\d])")

_ID_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
_ID_CHECK = "10X98765432"


def _entropy(text: str) -> float:
    counts = {}
    for ch in text:
        counts[ch] = counts.get(ch, 0) + 1
    total = len(text)
    return -sum(c / total * math.log2(c / total) for c in counts.values())


def _looks_like_secret_token(token: str) -> bool:
    if "/" in token and token.count("/") >= 2:  # URL path segments, not a key
        return False
    classes = sum([any(c.islower() for c in token), any(c.isupper() for c in token), any(c.isdigit() for c in token)])
    return classes == 3 and _entropy(token) >= 3.5


def _valid_id_card(number: str) -> bool:
    total = sum(int(d) * w for d, w in zip(number[:17], _ID_WEIGHTS))
    return _ID_CHECK[total % 11] == number[17].upper()


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


class SensitiveContentGuard:
    """Rejects passwords, keys, tokens, ID numbers and bank card numbers (AC-16)."""

    @staticmethod
    def find(text: str) -> str | None:
        """Return the rule name that matched, or None."""
        if not text:
            return None
        for pattern in _KEY_PATTERNS:
            if pattern.search(text):
                return "key_prefix"
        if _PASSWORD_ASSIGNMENT.search(text):
            return "password_assignment"
        for match in _ID_CARD.finditer(text):
            if _valid_id_card(match.group(1)):
                return "id_card"
        for match in _CARD_CANDIDATE.finditer(text):
            digits = re.sub(r"[ \-]", "", match.group(1))
            if 13 <= len(digits) <= 19 and _luhn(digits):
                return "bank_card"
        for match in _TOKEN_CANDIDATE.finditer(text):
            if _looks_like_secret_token(match.group(0)):
                return "high_entropy"
        return None

    @classmethod
    def check(cls, text: str) -> None:
        if cls.find(text):
            raise MemoryContentSensitiveError()


_RELATIVE_TIME = re.compile(
    r"(今天|今日|今晚|今早|明天|明日|明早|明晚|后天|大后天|昨天|昨日|前天|"
    r"(?:下|上|这|本)(?:个)?(?:周|星期|礼拜)[一二三四五六日天末]?|"
    r"(?:下|上|这|本)(?:个)?月|月底前?|今年|明年|去年|"
    r"[一二三四五六七八九十两\d]+\s*(?:天|周|个月|星期)(?:后|以后|之后|前|以前)|"
    r"\btoday\b|\btonight\b|\btomorrow\b|\byesterday\b|"
    r"\b(?:next|last|this)\s+(?:week|month|year|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b|"
    r"\bin\s+\d+\s+(?:days?|weeks?|months?)\b|\b\d+\s+(?:days?|weeks?)\s+ago\b)",
    re.IGNORECASE,
)


def check_relative_time(text: str) -> None:
    """AC-14: the model converts relative time to dates; code rejects leftovers."""
    if text and _RELATIVE_TIME.search(text):
        raise MemoryContentRelativeTimeError()


def validate_item(content: str | None, item_type: str | None) -> str:
    """Validate one item; returns the stripped content or raises a 121xx error."""
    text = (content or "").strip()
    if not text:
        raise MemoryContentEmptyError()
    if len(text) > MAX_CONTENT_CHARS:
        raise MemoryContentTooLongError()
    if item_type not in ITEM_TYPES:
        raise MemoryContentTypeInvalidError()
    SensitiveContentGuard.check(text)
    check_relative_time(text)
    return text


def validate_detail(detail: str | None) -> None:
    """Detail bodies have no length limit but must not carry secrets or relative time."""
    if detail:
        SensitiveContentGuard.check(detail)
        check_relative_time(detail)
