# ruff: noqa: RUF001
import asyncio

import pytest

from bisheng.common.stream_errors import (
    StreamRetryEvent,
    classify_stream_error,
    retry_async_stream,
    stream_error_payload,
)


class ProviderAuthenticationError(RuntimeError):
    status_code = 401


class ProviderRateLimitError(RuntimeError):
    status_code = 429


class ProviderRequestError(RuntimeError):
    status_code = 400


def test_model_error_uses_safe_title_and_never_exposes_raw_exception():
    error = RuntimeError("provider=https://internal.example token=secret traceback")

    info = classify_stream_error(error, stage="model")
    payload = stream_error_payload(error, stage="model")

    assert info.kind == "model"
    assert info.title == "模型请求被拒绝"
    assert info.retryable is False
    assert payload["title"] == "模型请求被拒绝"
    assert payload["reason"] == "这次模型请求被拒绝，暂时无法判断具体原因。"
    assert len(payload["reason"]) <= 160
    assert "secret" not in str(payload)
    assert "internal.example" not in str(payload)
    assert "exception" not in payload.get("data", {})


@pytest.mark.parametrize(
    ("message", "title", "retryable"),
    [
        (
            "Error code: 400 - Range of input length should be [1, 30720]",
            "内容超出模型长度",
            False,
        ),
        (
            "Error code: 404 - {'error': {'message': 'Model not exist.', 'code': 'model_not_found'}}",
            "当前模型不可用",
            False,
        ),
        (
            "Error code: 403 - {'error': {'message': 'Access denied.', 'code': 'access_denied'}}",
            "模型没有调用权限",
            False,
        ),
    ],
)
def test_provider_model_rejections_use_specific_copy(message, title, retryable):
    info = classify_stream_error(RuntimeError(message), stage="model")

    assert info.title == title
    assert info.retryable is retryable
    assert info.kind == "model"
    assert len(info.reason) <= 160
    assert "token" not in info.reason.lower()


def test_unknown_model_rejection_appends_safe_trace_id():
    from bisheng.core.logger import trace_id_var

    token = trace_id_var.set("trace-1")
    try:
        payload = stream_error_payload(RuntimeError("upstream rejected"), stage="model")
    finally:
        trace_id_var.reset(token)

    assert payload["reason"] == "这次模型请求被拒绝，暂时无法判断具体原因。追踪号：trace-1。"
    assert payload["retryable"] is False


@pytest.mark.parametrize(
    ("error", "stage", "kind", "title", "retryable"),
    [
        (TimeoutError("timed out"), "model", "network", "网络连接失败", True),
        (ProviderRateLimitError("rate limit"), "model", "rate_limit", "请求过于频繁", True),
        (ProviderAuthenticationError("api_key=secret"), "model", "model", "模型没有调用权限", False),
        (ProviderAuthenticationError("api_key=secret"), "system", "auth", "认证或权限失败", False),
        (ProviderRequestError("bad request"), "model", "model", "模型请求被拒绝", False),
        (RuntimeError("vector unavailable"), "retrieval", "retrieval", "知识检索失败", False),
        (RuntimeError("not ready"), "document", "document", "文档暂不可用", False),
        (RuntimeError("missing model"), "config", "config", "问答配置异常", False),
    ],
)
def test_error_categories_are_stable(error, stage, kind, title, retryable):
    info = classify_stream_error(error, stage=stage)

    assert (info.kind, info.title, info.retryable) == (kind, title, retryable)


async def test_retry_async_stream_retries_twice_before_success():
    attempts = 0
    sleeps: list[float] = []

    async def stream():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise TimeoutError("model timed out")
        yield "answer"

    async def fake_sleep(delay: float):
        sleeps.append(delay)

    items = [
        item
        async for item in retry_async_stream(
            stream,
            stage="model",
            max_retries=2,
            sleep=fake_sleep,
        )
    ]

    assert attempts == 3
    assert items == [
        StreamRetryEvent(attempt=1, max_attempts=2, retry_after_ms=500),
        StreamRetryEvent(attempt=2, max_attempts=2, retry_after_ms=1000),
        "answer",
    ]
    assert sleeps == [0.5, 1.0]


async def test_retry_async_stream_does_not_retry_after_partial_output():
    attempts = 0

    async def stream():
        nonlocal attempts
        attempts += 1
        yield "partial"
        raise TimeoutError("model timed out")

    received = []
    with pytest.raises(TimeoutError):
        async for item in retry_async_stream(stream, stage="model", max_retries=2):
            received.append(item)

    assert received == ["partial"]
    assert attempts == 1


async def test_retry_async_stream_stops_after_two_retries():
    attempts = 0
    received = []

    async def stream():
        nonlocal attempts
        attempts += 1
        raise TimeoutError("model timed out")
        yield

    async def no_sleep(_: float):
        return None

    with pytest.raises(TimeoutError):
        async for item in retry_async_stream(
            stream,
            stage="model",
            max_retries=2,
            sleep=no_sleep,
        ):
            received.append(item)

    assert attempts == 3
    assert received == [
        StreamRetryEvent(attempt=1, max_attempts=2, retry_after_ms=500),
        StreamRetryEvent(attempt=2, max_attempts=2, retry_after_ms=1000),
    ]


async def test_retry_async_stream_ignores_empty_metadata_chunks_for_output_boundary():
    attempts = 0

    async def stream():
        nonlocal attempts
        attempts += 1
        yield {"content": ""}
        if attempts == 1:
            raise TimeoutError("model timed out")
        yield {"content": "answer"}

    async def no_sleep(_: float):
        return None

    received = [
        item
        async for item in retry_async_stream(
            stream,
            stage="model",
            max_retries=2,
            sleep=no_sleep,
            is_output=lambda item: bool(item["content"]),
        )
    ]

    assert attempts == 2
    assert received == [
        {"content": ""},
        StreamRetryEvent(attempt=1, max_attempts=2, retry_after_ms=500),
        {"content": ""},
        {"content": "answer"},
    ]


async def test_retry_async_stream_propagates_cancellation_without_retry():
    attempts = 0

    async def stream():
        nonlocal attempts
        attempts += 1
        raise asyncio.CancelledError
        yield

    with pytest.raises(asyncio.CancelledError):
        async for _ in retry_async_stream(stream, stage="model", max_retries=2):
            pass

    assert attempts == 1
