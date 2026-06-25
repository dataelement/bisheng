"""Daily-mode chat rate-limit surfacing (限流文案统一).

The workstation agent-chat ``except`` branch classifies an upstream throttling
exception to RATE_LIMIT and emits the ``LLMRateLimitError(12046)`` SSE envelope,
so the frontend renders the friendly ``api_errors.12046`` copy instead of the raw
provider 500. This pins that wiring (classification + error code + SSE shape)
without standing up the full chat generator.
"""

import json

import openai

from bisheng.common.errcode.workstation import LLMRateLimitError
from bisheng.common.services.llm_error_classifier import ErrorType, label_error, unwrap

# The exact provider strings the product flagged as throttling.
_THROTTLING_STRINGS = (
    "Requests rate limit exceeded",
    "You exceeded your current requests list",
    "Allocated quota exceeded",
    "You exceeded your current quota",
    "Request rate increased too quickly",
)


def test_throttling_strings_classify_to_rate_limit():
    for msg in _THROTTLING_STRINGS:
        assert label_error(unwrap(RuntimeError(msg))) is ErrorType.RATE_LIMIT, msg


def test_classification_follows_cause_chain():
    """chat_service hands the caught exc straight to label_error(unwrap(exc)); a
    throttling RateLimitError wrapped by a higher layer must still be seen."""
    inner = openai.RateLimitError.__new__(openai.RateLimitError)
    inner.message = "Requests rate limit exceeded"
    inner.code = "rate_limit_exceeded"
    inner.body = None
    wrapper = RuntimeError("agent chat failed")
    wrapper.__cause__ = inner
    assert label_error(unwrap(wrapper)) is ErrorType.RATE_LIMIT


def test_llm_rate_limit_sse_envelope_is_12046():
    sse = LLMRateLimitError().to_sse_event_instance_str()
    # contract: "event: error\ndata: {json}\n\n" — consumed by useAiChatSSE error listener
    assert sse.startswith("event: error\n")
    payload = json.loads(sse.split("data: ", 1)[1].strip())
    assert payload["status_code"] == 12046


def test_genuine_quota_not_misrouted_to_rate_limit():
    """Billing exhaustion must NOT take the 12046 path (would wrongly say 'try later')."""
    assert label_error(unwrap(RuntimeError("insufficient_quota"))) is ErrorType.QUOTA_EXHAUSTED
