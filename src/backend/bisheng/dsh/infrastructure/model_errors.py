"""Bounded diagnostic codes; never persist provider messages or credentials."""

import re

import httpx
from langchain_core.exceptions import ContextOverflowError
from openai import APIConnectionError, APITimeoutError


def provider_failure_code(value):
    code = value.get("code") if isinstance(value, dict) else None
    return {
        "invalid_api_key": "upstream_authentication_failed",
        "InvalidApiKey": "upstream_authentication_failed",
        "rate_limit_exceeded": "upstream_rate_limited",
        "insufficient_quota": "upstream_quota_exhausted",
        "context_length_exceeded": "context_length_exceeded",
        "server_error": "upstream_server_error",
    }.get(code if isinstance(code, str) else None, "upstream_error")


def _error_chain(error):
    seen = set()
    for _ in range(8):
        if error is None or id(error) in seen:
            break
        seen.add(id(error))
        yield error
        error = error.__cause__ or error.__context__


def is_context_length_error(error):
    # LangChain's HTTP-200 stream overflow keeps the gateway's generic code.
    # Its typed exception is authoritative, including through provider wrappers.
    return any(
        isinstance(item, ContextOverflowError) or getattr(item, "code", None) == "context_length_exceeded"
        for item in _error_chain(error)
    )


def model_failure_code(exception):
    if is_context_length_error(exception):
        return "context_length_exceeded"
    for error in _error_chain(exception):
        if isinstance(error, (TimeoutError, httpx.TimeoutException, APITimeoutError)):
            return "upstream_timeout"
        status = getattr(error, "status_code", None)
        response = getattr(error, "response", None)
        if status is None:
            status = (
                response.get("status_code") if isinstance(response, dict) else getattr(response, "status_code", None)
            )
        # Tongyi's adapter converts HTTP 400/401 into ValueError with labeled fields.
        if status is None and isinstance(error, ValueError):
            match = re.search(r"(?:^|\n)\s*status_code:\s*([45][0-9]{2})(?:\s|$)", str(error)[:4096])
            status = int(match[1]) if match else None
        if isinstance(status, int) and 400 <= status <= 599:
            return f"upstream_http_{status}"
        if isinstance(error, (ConnectionError, httpx.NetworkError, APIConnectionError)):
            return "upstream_connection_failed"
        if getattr(error, "ClientCode", None) == "upstream_timeout":
            return "upstream_timeout"
    return "upstream_error"
