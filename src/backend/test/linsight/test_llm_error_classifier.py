"""Unit tests for the Linsight LLM error classifier (灵思LLM容错).

Covers the two layers separately:
- ``classify_behavior`` (vendor-agnostic RETRYABLE / FAIL_FAST / DEGRADABLE)
- ``label_error`` / ``label_text`` (best-effort friendly label)
plus the order-sensitivity trap (quota must win over the 429 rate-limit branch)
and the cross-vendor content-filter signatures.
"""

import openai
import pytest

from bisheng.common.services.llm_error_classifier import (
    Behavior,
    ErrorType,
    classify_behavior,
    classify_for_event,
    label_error,
    label_text,
    unwrap,
)


def make_exc(cls, *, message="", code=None, body=None, status_code=None):
    """Build an openai exception instance without running its __init__.

    isinstance checks still hold; the classifier only reads message/code/body/
    status_code attributes.
    """
    exc = cls.__new__(cls)
    exc.message = message
    exc.code = code
    exc.body = body
    if status_code is not None:
        exc.status_code = status_code
    return exc


# --------------------------------------------------------------------------- #
# Layer 1 — behaviour bucket
# --------------------------------------------------------------------------- #


def test_content_filter_is_degradable():
    exc = make_exc(
        openai.BadRequestError,
        message="Output data may contain inappropriate content",
        code="data_inspection_failed",
        body={"code": "data_inspection_failed", "message": "inappropriate content"},
        status_code=400,
    )
    assert classify_behavior(exc) is Behavior.DEGRADABLE


def test_quota_is_fail_fast_even_on_429():
    """A quota error can arrive as HTTP 429 — it must NOT be treated as retryable."""
    exc = make_exc(
        openai.RateLimitError,
        message="You exceeded your current quota, insufficient_quota",
        code="insufficient_quota",
        status_code=429,
    )
    assert classify_behavior(exc) is Behavior.FAIL_FAST


def test_plain_rate_limit_is_retryable():
    exc = make_exc(
        openai.RateLimitError,
        message="Rate limit reached, please slow down",
        code="rate_limit_exceeded",
        status_code=429,
    )
    assert classify_behavior(exc) is Behavior.RETRYABLE


def test_timeout_and_connection_are_retryable():
    assert classify_behavior(make_exc(openai.APITimeoutError, message="timeout")) is Behavior.RETRYABLE
    assert classify_behavior(make_exc(openai.APIConnectionError, message="conn reset")) is Behavior.RETRYABLE
    assert classify_behavior(TimeoutError("slow")) is Behavior.RETRYABLE
    assert classify_behavior(ConnectionError("reset")) is Behavior.RETRYABLE


def test_5xx_is_retryable():
    assert classify_behavior(make_exc(openai.InternalServerError, status_code=500)) is Behavior.RETRYABLE
    # bare APIStatusError with a 5xx status (not the InternalServerError subclass)
    assert classify_behavior(make_exc(openai.APIStatusError, status_code=503)) is Behavior.RETRYABLE


def test_auth_and_permission_are_fail_fast():
    assert classify_behavior(make_exc(openai.AuthenticationError, status_code=401)) is Behavior.FAIL_FAST
    assert classify_behavior(make_exc(openai.PermissionDeniedError, status_code=403)) is Behavior.FAIL_FAST


def test_unknown_400_is_degradable_by_default():
    exc = make_exc(openai.BadRequestError, message="malformed request", status_code=400)
    assert classify_behavior(exc) is Behavior.DEGRADABLE
    # a non-API error also falls into the default skippable bucket
    assert classify_behavior(ValueError("boom")) is Behavior.DEGRADABLE


# --------------------------------------------------------------------------- #
# Layer 2 — friendly label (cross-vendor content-filter signatures)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "kwargs",
    [
        # aliyun dashscope
        {"code": "data_inspection_failed", "message": "Output data may contain inappropriate content"},
        # openai
        {"code": "content_policy_violation", "message": "content policy"},
        # ctyun — string code carried in a non-standard body key, caught via keyword
        {"body": {"err_code": "TEXT_AUDIT_QUESTION_NOT_PASS"}, "message": "audit not_pass"},
        # baidu — numeric code in error_code body field (exact match)
        {"body": {"error_code": "336005"}, "message": "output filtered"},
        # zhipu numeric code
        {"code": "1301", "message": "blocked by safety"},
        # generic chinese guardrail text
        {"message": "命中内容安全策略，已拦截"},
    ],
)
def test_content_filter_label_across_vendors(kwargs):
    exc = make_exc(openai.BadRequestError, status_code=400, **kwargs)
    assert label_error(exc) is ErrorType.CONTENT_FILTER


def test_quota_label():
    exc = make_exc(openai.RateLimitError, message="insufficient_quota", status_code=429)
    assert label_error(exc) is ErrorType.QUOTA_EXHAUSTED


def test_network_and_service_labels():
    assert label_error(make_exc(openai.APITimeoutError, message="t")) is ErrorType.NETWORK_TIMEOUT
    assert label_error(make_exc(openai.InternalServerError, status_code=500)) is ErrorType.SERVICE_UNAVAILABLE


def test_rate_limit_and_auth_labels():
    assert label_error(make_exc(openai.RateLimitError, message="slow down", status_code=429)) is ErrorType.RATE_LIMIT
    assert label_error(make_exc(openai.AuthenticationError, status_code=401)) is ErrorType.AUTH_ERROR


def test_unknown_label_falls_through():
    assert label_error(ValueError("boom")) is ErrorType.UNKNOWN


def test_label_text_best_effort():
    assert label_text("Output data may contain inappropriate content") is ErrorType.CONTENT_FILTER
    assert label_text("insufficient_quota: pay up") is ErrorType.QUOTA_EXHAUSTED
    assert label_text("some random failure") is ErrorType.UNKNOWN


# --------------------------------------------------------------------------- #
# Rate-limit / throttling — RPM / TPM / burst signatures (限流友好文案)
# --------------------------------------------------------------------------- #

# The five provider strings the product flagged as "limit reached, try later".
# All must land on RATE_LIMIT + RETRYABLE whether they arrive as a standard
# RateLimitError, a non-standard BadRequestError, or a bare string.
_RATE_LIMIT_STRINGS = [
    "Requests rate limit exceeded",
    "You exceeded your current requests list",
    "Allocated quota exceeded",
    "You exceeded your current quota",
    "Request rate increased too quickly",
]


@pytest.mark.parametrize("message", _RATE_LIMIT_STRINGS)
def test_rate_limit_strings_label_rate_limit(message):
    # standard 429 RateLimitError
    assert label_error(make_exc(openai.RateLimitError, message=message, status_code=429)) is ErrorType.RATE_LIMIT
    # non-standard: throttling text carried by a BadRequestError / 200 body
    assert label_error(make_exc(openai.BadRequestError, message=message, status_code=400)) is ErrorType.RATE_LIMIT


@pytest.mark.parametrize("message", _RATE_LIMIT_STRINGS)
def test_rate_limit_strings_label_text(message):
    assert label_text(message) is ErrorType.RATE_LIMIT


@pytest.mark.parametrize("message", _RATE_LIMIT_STRINGS)
def test_rate_limit_strings_are_retryable(message):
    # body-embedded throttling (not a RateLimitError) must still retry, not degrade
    assert classify_behavior(make_exc(openai.BadRequestError, message=message, status_code=400)) is Behavior.RETRYABLE


def test_exceeded_current_quota_is_throttling_not_billing():
    """Regression: 'exceeded your current quota' moved out of the quota bucket to
    rate-limit (product decision: TPM throttling, not unrecoverable billing)."""
    exc = make_exc(openai.BadRequestError, message="You exceeded your current quota", status_code=400)
    assert label_error(exc) is ErrorType.RATE_LIMIT
    assert classify_behavior(exc) is Behavior.RETRYABLE


def test_genuine_billing_exhaustion_stays_quota():
    """Balance / credit exhaustion must still FAIL_FAST + QUOTA_EXHAUSTED."""
    for msg in ("insufficient_quota", "账户余额不足", "您已欠费", "额度不足"):
        exc = make_exc(openai.RateLimitError, message=msg, status_code=429)
        assert classify_behavior(exc) is Behavior.FAIL_FAST, msg
        assert label_error(exc) is ErrorType.QUOTA_EXHAUSTED, msg


def test_quota_beats_rate_limit_when_both_present():
    """Order invariant: a message carrying BOTH a billing signal and a throttle
    word must FAIL_FAST as quota, never retry as a transient rate limit."""
    exc = make_exc(
        openai.RateLimitError,
        message="rate limit hit; also insufficient_quota — please top up",
        status_code=429,
    )
    assert classify_behavior(exc) is Behavior.FAIL_FAST
    assert label_error(exc) is ErrorType.QUOTA_EXHAUSTED


# --------------------------------------------------------------------------- #
# unwrap + classify_for_event
# --------------------------------------------------------------------------- #


def test_unwrap_follows_cause_chain():
    inner = make_exc(openai.BadRequestError, code="data_inspection_failed", status_code=400)
    try:
        try:
            raise inner
        except openai.BadRequestError as cause:
            raise RuntimeError("Agent task execution failed") from cause
    except RuntimeError as wrapper:
        assert unwrap(wrapper) is inner


def test_classify_for_event_unwraps_and_labels():
    inner = make_exc(
        openai.BadRequestError,
        message="inappropriate content",
        code="data_inspection_failed",
        status_code=400,
    )
    try:
        try:
            raise inner
        except openai.BadRequestError as cause:
            raise RuntimeError("Agent task execution failed: ...") from cause
    except RuntimeError as wrapper:
        result = classify_for_event(wrapper)
    assert result.error_type == ErrorType.CONTENT_FILTER.value
    assert result.error_code == 11090
    assert "Agent task execution failed" in result.detail


def test_classify_for_event_accepts_bare_string():
    result = classify_for_event("Task execution failed: inappropriate content detected")
    assert result.error_type == ErrorType.CONTENT_FILTER.value
    assert result.error_code == 11090
    assert result.detail.startswith("Task execution failed")
