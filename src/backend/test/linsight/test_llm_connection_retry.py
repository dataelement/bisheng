"""Keep transport failures retryable across SDK wrapping and stored task replay."""

import httpcore
import httpx
import openai
import pytest

from bisheng.common.services.llm_error_classifier import (
    Behavior,
    ErrorType,
    classify_behavior,
    classify_for_event,
    label_error,
)
from bisheng.linsight.domain.models.linsight_session_version import (
    LinsightSessionVersion,
    SessionVersionStatusEnum,
)
from bisheng.linsight.domain.services.task_failure_payload import task_failure_payload


def wrapped_connection():
    core = httpcore.ConnectError("All connection attempts failed")
    transport = httpx.ConnectError("All connection attempts failed")
    transport.__cause__ = core
    sdk = openai.APIConnectionError(request=httpx.Request("POST", "http://mock.test:8000/v1/chat/completions"))
    sdk.__cause__ = transport
    task = RuntimeError("Agent task execution failed: Connection error.")
    task.__cause__ = sdk
    return task


def test_nested_sdk_connection_failure_is_service_unavailable():
    assert classify_for_event(wrapped_connection()).error_type == ErrorType.SERVICE_UNAVAILABLE.value


@pytest.mark.parametrize(
    "error", [httpx.ConnectError("All connection attempts failed"), ConnectionRefusedError(111, "Connect call failed")]
)
def test_direct_connection_errors_are_retryable_service_outages(error):
    assert classify_behavior(error) is Behavior.RETRYABLE
    assert label_error(error) is ErrorType.SERVICE_UNAVAILABLE


def test_sdk_timeout_keeps_its_label_even_when_its_cause_is_generic():
    error = openai.APITimeoutError(request=httpx.Request("POST", "http://mock.test/v1/chat/completions"))
    error.__cause__ = httpx.ReadTimeout("slow")
    assert classify_for_event(error).error_type == ErrorType.NETWORK_TIMEOUT.value


def test_sdk_auth_error_is_not_changed_into_a_retryable_transport_cause():
    request = httpx.Request("POST", "http://mock.test/v1/chat/completions")
    error = openai.AuthenticationError("invalid credentials", response=httpx.Response(401, request=request), body={})
    error.__cause__ = httpx.ConnectError("connection refused")
    assert classify_for_event(error).error_type == ErrorType.AUTH_ERROR.value


def legacy_failure(error_type="unknown", code=11090):
    return {
        "error_type": error_type,
        "error_code": code,
        "detail": "TaskExecutionError: model=mock-500: Connection error. <- ConnectionRefusedError: [Errno 111] Connect call failed ('<host>', 8000)",
        "error_message": "Service request failed (model_service)",
    }


def test_saved_unknown_connection_failure_is_recovered_for_task_replay():
    raw = legacy_failure()
    assert task_failure_payload(raw)["error_type"] == "service_unavailable"
    assert raw["error_type"] == "unknown"


def test_failed_version_public_read_recovers_the_same_classification():
    version = LinsightSessionVersion(
        session_id="session",
        user_id=1,
        question="test",
        status=SessionVersionStatusEnum.FAILED,
        output_result=legacy_failure(),
    )
    assert version.public_dump()["output_result"]["error_type"] == "service_unavailable"
    assert version.output_result["error_type"] == "unknown"


@pytest.mark.parametrize(
    "kind,code", [("auth_error", 11090), ("content_filter", 11090), ("quota_exhausted", 11090), ("unknown", 11091)]
)
def test_replay_never_relaxes_explicit_terminal_or_platform_errors(kind, code):
    assert task_failure_payload(legacy_failure(kind, code))["error_type"] == kind
