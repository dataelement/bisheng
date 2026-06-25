"""Classify LLM / provider exceptions for fault tolerance + user-facing copy.

Shared by Linsight task mode (resilience middleware + ``TaskErrorCard``) and
daily-mode chat (workstation), so it lives in ``common`` rather than under any
single domain module.

Two intentionally decoupled layers (design: 灵思LLM容错与失败态友好交互):

1. ``classify_behavior(exc) -> Behavior`` — drives the resilience middleware.
   Vendor-AGNOSTIC: decided purely by HTTP status + standard exception types
   (OpenAI SDK / httpx / stdlib). It uses NO per-vendor error codes. Content
   moderation ("safety guardrail") errors need no dedicated bucket — they fall
   into the default ``DEGRADABLE`` bucket like any other non-retryable client
   error. This layer is what makes the resilience behaviour stable across every
   model vendor without per-vendor adapters.

2. ``label_error(exc) -> ErrorType`` — drives the user-facing copy ONLY.
   Best-effort: a single flat shared signature set (keywords ∪ known vendor
   codes) tags ``content_filter`` etc. A miss simply degrades to a generic
   ``unknown`` label (still rendered as friendly localized copy on the
   frontend) — it never changes fault-tolerance behaviour and never raises.

Adding a new vendor only ever means extending the flat signature constants
below — never writing a new class or per-vendor branch.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

import openai

from bisheng.common.errcode.linsight import LinsightBishengLLMError


class Behavior(str, enum.Enum):
    """Coarse fault-tolerance bucket consumed by the resilience middleware."""

    RETRYABLE = "retryable"
    """Transient (network / 5xx / non-quota 429) — exponential-backoff retry."""

    FAIL_FAST = "fail_fast"
    """Unrecoverable (quota / auth / permission) — fail immediately, no retry,
    no degrade-budget waste."""

    DEGRADABLE = "degradable"
    """Non-retryable but skippable (content filter, plain 400, anything else) —
    the middleware degrades the step (subagent) or fails cleanly (main graph)."""


class ErrorType(str, enum.Enum):
    """Fine-grained label consumed ONLY for the user-facing failure copy."""

    CONTENT_FILTER = "content_filter"
    QUOTA_EXHAUSTED = "quota_exhausted"
    AUTH_ERROR = "auth_error"
    RATE_LIMIT = "rate_limit"
    SERVICE_UNAVAILABLE = "service_unavailable"
    NETWORK_TIMEOUT = "network_timeout"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Flat shared signatures — extend these (and only these) for a new vendor.
# ---------------------------------------------------------------------------

# Quota / billing EXHAUSTION (balance/credit run out — will NOT recover). MUST be
# checked before rate-limit, because a quota error can surface as HTTP 429 just
# like a transient rate limit, but its remedy is "top up", not "retry later".
# Kept narrow so transient quota *throttling* (see _RATE_LIMIT_SIGNATURES) is not
# mislabeled as an unrecoverable billing error.
_QUOTA_SIGNATURES: tuple[str, ...] = (
    "insufficient_quota",
    "insufficient quota",
    "arrearage",
    "quota used up",
    "quota_used_up",
    "余额不足",
    "欠费",
    "额度不足",
    "配额",
)

# Transient throttling — RPM (requests/min), TPM (tokens/min) and burst-rate
# protection. Recovers on its own → RETRYABLE + "service busy, try again later"
# copy. Distinct from quota EXHAUSTION above: "exceeded your current quota" /
# "allocated quota exceeded" are treated as throttling (product decision), while
# "insufficient_quota" / 余额不足 / 欠费 stay in the exhaustion bucket. Checked
# AFTER _is_quota so genuine billing exhaustion is never retried.
_RATE_LIMIT_SIGNATURES: tuple[str, ...] = (
    "rate limit",
    "rate_limit",
    "ratelimit",
    "requests rate limit",
    "exceeded your current requests",  # "You exceeded your current requests list"
    "request rate increased too quickly",
    "allocated quota exceeded",
    "exceeded your current quota",  # throttling, not billing (per product decision)
    "too many requests",
    "请求过于频繁",
    "限流",
)

# Content-moderation / safety-guardrail codes across mainstream vendors:
# Aliyun DashScope (data_inspection_failed / inappropriate_content),
# Baidu Qianfan (336003/336005), Zhipu (1301), MiniMax (2013),
# iFlytek Spark (10019/10014), Ctyun (600003 / TEXT_AUDIT_QUESTION_NOT_PASS),
# OpenAI (content_policy_violation / content_filter). Matched case-insensitively.
_CONTENT_FILTER_CODES: frozenset[str] = frozenset(
    {
        "data_inspection_failed",
        "datainspectionfailed",
        "inappropriate_content",
        "content_policy_violation",
        "content_filter",
        "text_audit_question_not_pass",
        "600003",
        "336003",
        "336005",
        "1301",
        "2013",
        "10019",
        "10014",
    }
)

# Substrings matched against code + message. Kept reasonably specific so a miss
# (generic label) is preferred over a false positive — either way behaviour is
# unaffected (label only).
_CONTENT_FILTER_KEYWORDS: tuple[str, ...] = (
    "inappropriate content",
    "inappropriate_content",
    "data_inspection",
    "data inspection",
    "data may contain",
    "content policy",
    "content_policy",
    "content filter",
    "content_filter",
    "not_pass",
    "risk control",
    "risk_control",
    "敏感",
    "安全策略",
    "内容安全",
    "违规内容",
    "审核不通过",
    "风控",
)


# ---------------------------------------------------------------------------
# Exception field extraction helpers
# ---------------------------------------------------------------------------


# Body keys various OpenAI-compatible vendors use to carry their error code.
_CODE_KEYS: tuple[str, ...] = ("code", "error_code", "err_code", "errcode", "sub_code")


def _exc_code(exc: BaseException) -> str | None:
    """Best-effort provider error ``code`` (OpenAI SDK ``.code`` or a body code key).

    Vendors disagree on the field name (Baidu uses ``error_code``, others ``code``),
    so a small set of common keys is probed. Used for EXACT matches against the
    known-code set only — never substring — to avoid false positives.
    """
    code = getattr(exc, "code", None)
    if code in (None, ""):
        body = getattr(exc, "body", None)
        if isinstance(body, dict):
            for key in _CODE_KEYS:
                if body.get(key) not in (None, ""):
                    code = body.get(key)
                    break
    return str(code).strip().lower() if code not in (None, "") else None


def _exc_text(exc: BaseException) -> str:
    """Lower-cased blob of message + code + all body values + str(exc).

    All body values are folded in so string codes (e.g. Ctyun's
    ``TEXT_AUDIT_QUESTION_NOT_PASS``) are reachable by keyword matching regardless
    of which body key holds them.
    """
    parts: list[str] = []
    msg = getattr(exc, "message", None)
    if msg:
        parts.append(str(msg))
    code = getattr(exc, "code", None)
    if code is not None:
        parts.append(str(code))
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        for value in body.values():
            if value not in (None, ""):
                parts.append(str(value))
    parts.append(str(exc))
    return " ".join(parts).lower()


def _status_code(exc: BaseException) -> int | None:
    status = getattr(exc, "status_code", None)
    return status if isinstance(status, int) else None


def _is_quota(exc: BaseException) -> bool:
    text = _exc_text(exc)
    return any(sig in text for sig in _QUOTA_SIGNATURES)


def _is_rate_limit(exc: BaseException) -> bool:
    """Keyword rate-limit/throttle signal — catches non-standard 429s and limits
    embedded in a 200 body that never surface as ``openai.RateLimitError``."""
    text = _exc_text(exc)
    return any(sig in text for sig in _RATE_LIMIT_SIGNATURES)


def _is_content_filter(exc: BaseException) -> bool:
    if isinstance(exc, openai.ContentFilterFinishReasonError):
        return True
    code = _exc_code(exc)
    if code and code in _CONTENT_FILTER_CODES:
        return True
    text = _exc_text(exc)
    return any(keyword in text for keyword in _CONTENT_FILTER_KEYWORDS)


def unwrap(error: BaseException) -> BaseException:
    """Follow the ``__cause__`` chain to the original provider exception.

    ``task_exec`` wraps the real cause in ``TaskExecutionError(...) from e``;
    classification should run on the root cause, not the wrapper.
    """
    current = error
    depth = 0
    while getattr(current, "__cause__", None) is not None and depth < 10:
        current = current.__cause__  # type: ignore[assignment]
        depth += 1
    return current


# ---------------------------------------------------------------------------
# Layer 1 — behaviour bucket (vendor-agnostic; drives the middleware)
# ---------------------------------------------------------------------------


def classify_behavior(exc: BaseException) -> Behavior:
    """Bucket an exception into RETRYABLE / FAIL_FAST / DEGRADABLE.

    Pure HTTP-status + exception-type logic — zero per-vendor error codes.
    Order matters: quota (a 429 flavour that will not recover) is checked before
    the generic rate-limit retry branch.
    """
    # 1) FAIL_FAST — unrecoverable, do not retry and do not waste degrade budget.
    if _is_quota(exc):
        return Behavior.FAIL_FAST
    if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)):
        return Behavior.FAIL_FAST
    if _status_code(exc) in (401, 402, 403):
        return Behavior.FAIL_FAST

    # 2) RETRYABLE — transient network / server / non-quota rate-limit.
    if isinstance(exc, (openai.APITimeoutError, openai.APIConnectionError)):
        return Behavior.RETRYABLE
    if isinstance(exc, openai.RateLimitError):  # 429, non-quota (quota handled above)
        return Behavior.RETRYABLE
    if _is_rate_limit(exc):  # keyword rate-limit: non-standard 429 / body-embedded
        return Behavior.RETRYABLE
    if isinstance(exc, openai.InternalServerError):
        return Behavior.RETRYABLE
    status = _status_code(exc)
    if status is not None and 500 <= status < 600:
        return Behavior.RETRYABLE
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return Behavior.RETRYABLE

    # 3) DEGRADABLE — default bucket: content filter, plain 400, anything else.
    return Behavior.DEGRADABLE


# ---------------------------------------------------------------------------
# Layer 2 — error label (best-effort; drives the friendly UI copy only)
# ---------------------------------------------------------------------------


def label_text(text: str) -> ErrorType:
    """Label a bare error STRING when no exception object is available.

    Some failure paths only carry a message (e.g. the agent reported a failure
    answer that embeds the provider's moderation text). Best-effort keyword
    match; falls through to ``UNKNOWN``.
    """
    lowered = (text or "").lower()
    if any(keyword in lowered for keyword in _CONTENT_FILTER_KEYWORDS):
        return ErrorType.CONTENT_FILTER
    if any(sig in lowered for sig in _QUOTA_SIGNATURES):
        return ErrorType.QUOTA_EXHAUSTED
    if any(sig in lowered for sig in _RATE_LIMIT_SIGNATURES):
        return ErrorType.RATE_LIMIT
    return ErrorType.UNKNOWN


def label_error(exc: BaseException) -> ErrorType:
    """Best-effort fine-grained label for the user-facing failure copy.

    A miss falls through to ``UNKNOWN`` (still rendered as friendly localized
    copy by the frontend). Never raises; never affects fault tolerance.
    """
    # content_filter is independent of the behaviour bucket (it lives in DEGRADABLE).
    if _is_content_filter(exc):
        return ErrorType.CONTENT_FILTER
    if _is_quota(exc):
        return ErrorType.QUOTA_EXHAUSTED
    if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)) or _status_code(exc) in (401, 403):
        return ErrorType.AUTH_ERROR
    if isinstance(exc, openai.RateLimitError) or _is_rate_limit(exc):
        return ErrorType.RATE_LIMIT
    if isinstance(exc, (openai.APITimeoutError, openai.APIConnectionError, TimeoutError, ConnectionError)):
        return ErrorType.NETWORK_TIMEOUT
    status = _status_code(exc)
    if isinstance(exc, openai.InternalServerError) or (status is not None and 500 <= status < 600):
        return ErrorType.SERVICE_UNAVAILABLE
    return ErrorType.UNKNOWN


@dataclass
class ClassifiedError:
    """Structured payload for the ``error_message`` event / ``output_result``."""

    error_type: str
    error_code: int
    detail: str


def classify_for_event(error: BaseException | str) -> ClassifiedError:
    """Unwrap → label → structured payload for ``_handle_task_failure``.

    Accepts either an exception (classified via the cause chain) or a bare
    message string (best-effort keyword label). ``error_code`` is the single
    umbrella ``LinsightBishengLLMError`` (11090); the frontend branches on
    ``error_type``, not the numeric code, so one code plus a precise
    ``error_type`` is enough and avoids minting a new code in a segment reserved
    for another concern.
    """
    if isinstance(error, str):
        return ClassifiedError(
            error_type=label_text(error).value,
            error_code=LinsightBishengLLMError.Code,
            detail=error,
        )
    return ClassifiedError(
        error_type=label_error(unwrap(error)).value,
        error_code=LinsightBishengLLMError.Code,
        detail=str(error),
    )
