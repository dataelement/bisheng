"""F063 StreamContentSafetyScanner: full-buffer checks every 100 code points."""

from __future__ import annotations

from bisheng.sensitive_word.domain.schemas import SensitiveWordCheckResult, SensitiveWordHit
from bisheng.sensitive_word.domain.services.sensitive_word_policy_service import (
    SensitiveWordPolicyService,
)
from bisheng.sensitive_word.domain.services.stream_scanner import StreamContentSafetyScanner

AUTO_REPLY = "当前对话内容违反相关规范，请修改后重新输入"


def _miss() -> SensitiveWordCheckResult:
    return SensitiveWordCheckResult(enabled=True, hits=[], auto_reply=AUTO_REPLY)


def _hit(word: str = "ab") -> SensitiveWordCheckResult:
    return SensitiveWordCheckResult(
        enabled=True,
        hits=[SensitiveWordHit(word=word, count=1)],
        auto_reply=AUTO_REPLY,
    )


def test_does_not_check_until_100_codepoints_then_scans_full_buffer(monkeypatch):
    calls: list[str] = []

    def _check(cls, tenant_id, business_type, text, **kwargs):
        calls.append(text)
        return _miss()

    monkeypatch.setattr(SensitiveWordPolicyService, "check_text", classmethod(_check))
    scanner = StreamContentSafetyScanner(tenant_id=1)
    assert scanner.feed("x" * 99) is None
    assert calls == []
    result = scanner.feed("y")
    assert result is None
    assert len(calls) == 1
    assert calls[0] == "x" * 99 + "y"
    assert len(calls[0]) == 100


def test_next_check_is_at_200_not_101(monkeypatch):
    calls: list[str] = []

    def _check(cls, tenant_id, business_type, text, **kwargs):
        calls.append(text)
        return _miss()

    monkeypatch.setattr(SensitiveWordPolicyService, "check_text", classmethod(_check))
    scanner = StreamContentSafetyScanner(tenant_id=1)
    scanner.feed("a" * 100)
    assert len(calls) == 1
    assert scanner.feed("b") is None
    assert len(calls) == 1
    scanner.feed("c" * 99)
    assert len(calls) == 2
    assert len(calls[1]) == 200


def test_word_completing_on_the_100th_char_hits_full_text_check(monkeypatch):
    """A word that lands on the 99–100 boundary is visible because we scan the
    whole buffer, not a trailing window of 100 chars."""
    calls: list[str] = []

    def _check(cls, tenant_id, business_type, text, **kwargs):
        calls.append(text)
        if "敏感" in text:
            return _hit("敏感")
        return _miss()

    monkeypatch.setattr(SensitiveWordPolicyService, "check_text", classmethod(_check))
    scanner = StreamContentSafetyScanner(tenant_id=1)
    assert scanner.feed("x" * 98) is None
    assert scanner.feed("敏") is None
    result = scanner.feed("感")
    assert result is not None
    assert result.auto_reply == AUTO_REPLY
    assert len(calls) == 1
    assert calls[0].endswith("敏感")


def test_finish_checks_remainder_under_100(monkeypatch):
    calls: list[str] = []

    def _check(cls, tenant_id, business_type, text, **kwargs):
        calls.append(text)
        if "禁" in text:
            return _hit("禁")
        return _miss()

    monkeypatch.setattr(SensitiveWordPolicyService, "check_text", classmethod(_check))
    scanner = StreamContentSafetyScanner(tenant_id=1)
    assert scanner.feed("hello禁") is None
    assert calls == []
    result = scanner.finish()
    assert result is not None
    assert result.auto_reply == AUTO_REPLY
    assert calls == ["hello禁"]


def test_feed_does_not_see_thinking_strings(monkeypatch):
    """Guard: only final-answer deltas are fed. Thinking text with a banned
    word must never reach check_text from this scanner."""
    calls: list[str] = []

    def _check(cls, tenant_id, business_type, text, **kwargs):
        calls.append(text)
        return _hit("禁") if "禁" in text else _miss()

    monkeypatch.setattr(SensitiveWordPolicyService, "check_text", classmethod(_check))
    scanner = StreamContentSafetyScanner(tenant_id=1)
    thinking = "禁" * 120
    # Callers must not feed thinking; this test only feeds the clean answer.
    result = scanner.feed("干净回答" * 20)
    assert "禁" not in "".join(calls)
    assert thinking not in "".join(calls)
    assert result is None or "禁" not in (calls[0] if calls else "")


def test_after_hit_further_feed_does_not_rescan(monkeypatch):
    calls: list[str] = []

    def _check(cls, tenant_id, business_type, text, **kwargs):
        calls.append(text)
        return _hit("ab") if "ab" in text else _miss()

    monkeypatch.setattr(SensitiveWordPolicyService, "check_text", classmethod(_check))
    scanner = StreamContentSafetyScanner(tenant_id=1)
    hit = scanner.feed("x" * 98 + "ab")
    assert hit is not None
    assert hit.auto_reply == AUTO_REPLY
    assert len(calls) == 1
    again = scanner.feed("more tokens")
    assert again is hit
    assert len(calls) == 1
    assert scanner.finish() is hit
    assert len(calls) == 1
