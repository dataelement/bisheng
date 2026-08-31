from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from bisheng.llm.domain.const import LLMServerType

_TRANSIENT_CODES = {
    "throttling.ratequota",
    "throttling.allocationquota",
    "throttling.burstrate",
    "limitrequests",
    "limit_requests",
    "limit_burst_rate",
    "resourceexhausted",
    "insufficient_quota",
}

_TRANSIENT_TEXT = (
    "rate limit",
    "rate_limit",
    "too many requests",
    "requests rate limit exceeded",
    "allocated quota exceeded",
    "exceeded your current quota",
    "request rate increased too quickly",
    "请求过于频繁",
    "请求频率过高",
    "限流",
)

_PERMANENT_TEXT = (
    "arrearage",
    "in arrears",
    "余额不足",
    "欠费",
    "insufficient balance",
    "prepaidbilloverdue",
    "prepaid bill overdue",
    "postpaidbilloverdue",
    "postpaid bill overdue",
    "commoditynotpurchased",
    "commodity not purchased",
    "invalidapikey",
    "invalid api key",
    "authentication failed",
    "permission denied",
    "accessdenied",
    "datainspectionfailed",
    "data_inspection_failed",
    "inappropriate_content",
    "content safety",
    "content policy",
    "内容安全",
)

_TRUSTED_HOSTS = (
    "dashscope.aliyuncs.com",
    "dashscope-intl.aliyuncs.com",
    "bailian.aliyuncs.com",
)

_CODE_KEYS = {"code", "error_code", "err_code", "errcode", "sub_code", "type"}
_REQUEST_ID_KEYS = {"request_id", "requestid", "request-id", "x-request-id"}
_DETAIL_LIMIT = 512

_BEARER_RE = re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]+")
_SENSITIVE_FIELD = (
    r"api[_-]?key|access[_-]?token|authorization|password|secret|prompt|messages?|input|"
    r"context|attachments?|files?|tool(?:_args|_arguments)?"
)
_SENSITIVE_KEY_RE = re.compile(rf"(?i)^(?:{_SENSITIVE_FIELD})$")
_QUOTED_SECRET_FIELD_RE = re.compile(rf"(?i)({_SENSITIVE_FIELD})(\s*[:=]\s*)(['\"])(.*?)\3")
_SECRET_FIELD_RE = re.compile(rf"(?i)({_SENSITIVE_FIELD})(\s*[:=]\s*)[^\s,}}\]]+")


@dataclass(frozen=True, slots=True)
class AliyunRateLimitObservation:
    model_id: int
    provider_code: str | None
    request_id: str | None
    masked_detail: str


def _root_cause(exc: BaseException) -> BaseException:
    current = exc
    for _ in range(10):
        cause = getattr(current, "__cause__", None)
        if not isinstance(cause, BaseException):
            break
        current = cause
    return current


def _status_code(exc: BaseException) -> int | None:
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    response = getattr(exc, "response", None)
    response_status = getattr(response, "status_code", None)
    return response_status if isinstance(response_status, int) else None


def _walk_mapping(value: Any):
    if isinstance(value, dict):
        for key, nested in value.items():
            yield str(key), nested
            yield from _walk_mapping(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            yield from _walk_mapping(nested)


def _body(exc: BaseException) -> dict[str, Any]:
    body = getattr(exc, "body", None)
    return body if isinstance(body, dict) else {}


def _provider_code(exc: BaseException) -> str | None:
    direct = getattr(exc, "code", None)
    if direct not in (None, ""):
        return str(direct).strip()
    for key, value in _walk_mapping(_body(exc)):
        if key.lower() in _CODE_KEYS and value not in (None, "") and not isinstance(value, (dict, list, tuple)):
            return str(value).strip()
    return None


def _request_id(exc: BaseException) -> str | None:
    for attr in ("request_id", "requestId"):
        direct = getattr(exc, attr, None)
        if direct not in (None, ""):
            return str(direct).strip()
    for key, value in _walk_mapping(_body(exc)):
        if key.lower() in _REQUEST_ID_KEYS and value not in (None, ""):
            return str(value).strip()
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers:
        for header in ("x-request-id", "request-id"):
            value = headers.get(header)
            if value:
                return str(value).strip()
    return None


def _error_text(exc: BaseException) -> str:
    parts = [str(exc)]
    message = getattr(exc, "message", None)
    if message and str(message) not in parts:
        parts.append(str(message))
    code = _provider_code(exc)
    if code:
        parts.append(code)
    body = _body(exc)
    if body:
        parts.append(str(_sanitize_structured_detail(body)))
    return " ".join(parts)


def _sanitize_structured_detail(value: Any) -> Any:
    """Mask sensitive mapping values before their Python repr is generated."""
    if isinstance(value, dict):
        return {
            key: "***" if _SENSITIVE_KEY_RE.fullmatch(str(key)) else _sanitize_structured_detail(nested)
            for key, nested in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_structured_detail(item) for item in value]
    return value


def _mask_detail(detail: str) -> str:
    masked = _BEARER_RE.sub("Bearer ***", detail)
    masked = _QUOTED_SECRET_FIELD_RE.sub(
        lambda match: f"{match.group(1)}{match.group(2)}***",
        masked,
    )
    masked = _SECRET_FIELD_RE.sub(
        lambda match: f"{match.group(1)}{match.group(2)}***",
        masked,
    )
    return masked[:_DETAIL_LIMIT]


def _endpoint_host(server: Any) -> str:
    config = getattr(server, "config", None) or {}
    if not isinstance(config, dict):
        return ""
    endpoint = config.get("openai_api_base") or config.get("base_url") or config.get("endpoint") or ""
    if not isinstance(endpoint, str):
        return ""
    return (urlparse(endpoint).hostname or "").lower().rstrip(".")


def _is_aliyun_server(server: Any) -> bool:
    server_type = str(getattr(server, "type", "") or "").lower()
    if server_type == LLMServerType.QWEN.value:
        return True
    host = _endpoint_host(server)
    return any(host == trusted or host.endswith(f".{trusted}") for trusted in _TRUSTED_HOSTS)


class AliyunRateLimitClassifier:
    @classmethod
    def classify(
        cls,
        *,
        model: Any,
        server: Any,
        exc: BaseException,
    ) -> AliyunRateLimitObservation | None:
        root = _root_cause(exc)
        if not _is_aliyun_server(server) or _status_code(root) != 429:
            return None

        detail = _error_text(root)
        lowered = detail.lower()
        if any(signal in lowered for signal in _PERMANENT_TEXT):
            return None

        code = _provider_code(root)
        normalized_code = (code or "").lower()
        if normalized_code not in _TRANSIENT_CODES and not any(signal in lowered for signal in _TRANSIENT_TEXT):
            return None

        model_id = getattr(model, "id", None)
        if model_id is None:
            return None

        return AliyunRateLimitObservation(
            model_id=int(model_id),
            provider_code=code,
            request_id=_request_id(root),
            masked_detail=_mask_detail(detail),
        )
