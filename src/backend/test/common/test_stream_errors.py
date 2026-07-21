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
    assert info.title == "模型调用失败"
    assert info.retryable is True
    assert payload["title"] == "模型调用失败"
    assert payload["reason"] == "模型服务暂时不可用，请稍后重试。"
    assert "secret" not in str(payload)
    assert "internal.example" not in str(payload)
    assert "exception" not in payload.get("data", {})


@pytest.mark.parametrize(
    ("error", "stage", "kind", "title", "retryable"),
    [
        (TimeoutError("timed out"), "model", "network", "网络连接失败", True),
        (ProviderRateLimitError("rate limit"), "model", "rate_limit", "请求过于频繁", True),
        (ProviderAuthenticationError("api_key=secret"), "model", "auth", "认证或权限失败", False),
        (ProviderRequestError("bad request"), "model", "model", "模型调用失败", False),
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
