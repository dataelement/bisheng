"""AC-12: diagnostics retain bounded facts, never provider exception messages."""

import httpx
import pytest
from langchain_core.exceptions import ContextOverflowError
from langchain_openai.chat_models.base import OpenAIAPIContextOverflowError, OpenAIContextOverflowError
from openai import APIConnectionError, APITimeoutError, AuthenticationError

from bisheng.dsh.infrastructure.model_errors import model_failure_code, provider_failure_code


@pytest.mark.parametrize("kind", ["langchain", "stream", "http"])
def test_context_overflow_takes_precedence_over_generic_provider_code_and_status(kind):
    request = httpx.Request("POST", "https://fixture.invalid")
    if kind == "langchain":
        error = ContextOverflowError("private provider body")
    elif kind == "stream":
        error = OpenAIAPIContextOverflowError("private provider body", request=request, body={"code": "upstream_error"})
    else:
        error = OpenAIContextOverflowError(
            "private provider body", response=httpx.Response(400, request=request), body={"code": "upstream_error"}
        )
    assert model_failure_code(error) == "context_length_exceeded"
    wrapper = RuntimeError("private wrapper")
    wrapper.__cause__ = error
    assert model_failure_code(wrapper) == "context_length_exceeded"


def test_wrapped_context_overflow_uses_safe_public_error():
    from bisheng.common.errcode.dsh import DshContextLengthExceededError
    from bisheng.dsh.domain.services.model import DshModelService

    error = RuntimeError("private wrapper")
    error.__context__ = ContextOverflowError("private provider body")
    assert model_failure_code(error) == "context_length_exceeded"
    public = DshModelService._public_error(error)
    assert isinstance(public, DshContextLengthExceededError)
    assert "private" not in public.Msg


@pytest.mark.parametrize("status", [400, 401, 403, 404, 408, 429, 500, 504])
def test_http_status_facts(status):
    request = httpx.Request("POST", "https://fixture.invalid")
    error = httpx.HTTPStatusError("private-provider-body", request=request, response=httpx.Response(status))
    assert model_failure_code(error) == f"upstream_http_{status}"


def test_sdk_network_timeout_wrapped_and_unknown_facts():
    request = httpx.Request("POST", "https://fixture.invalid")
    assert (
        model_failure_code(AuthenticationError("private", response=httpx.Response(401, request=request), body=None))
        == "upstream_http_401"
    )
    for error in [TimeoutError("private"), httpx.ReadTimeout("private"), APITimeoutError(request=request)]:
        assert model_failure_code(error) == "upstream_timeout"
    assert model_failure_code(APIConnectionError(request=request)) == "upstream_connection_failed"
    outer = RuntimeError("private-wrapper")
    outer.__cause__ = httpx.ConnectError("private")
    assert model_failure_code(outer) == "upstream_connection_failed"
    outer.__cause__ = outer
    assert model_failure_code(outer) == "upstream_error"
    assert model_failure_code(RuntimeError("private-provider-body 401 timeout")) == "upstream_error"


def test_tongyi_labeled_status_and_native_failure_allowlist():
    assert (
        model_failure_code(ValueError("request_id: fixture\nstatus_code: 401\nmessage: private")) == "upstream_http_401"
    )
    assert model_failure_code(ValueError("private 401 unauthorized")) == "upstream_error"
    assert provider_failure_code({"code": "invalid_api_key", "message": "private"}) == "upstream_authentication_failed"
    assert provider_failure_code({"code": "insufficient_quota"}) == "upstream_quota_exhausted"
    assert provider_failure_code({"code": "private"}) == "upstream_error"
    assert provider_failure_code(None) == "upstream_error"
