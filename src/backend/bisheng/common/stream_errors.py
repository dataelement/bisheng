# ruff: noqa: RUF001
import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar

T = TypeVar("T")
SleepCallable = Callable[[float], Awaitable[None]]


@dataclass(frozen=True)
class StreamErrorInfo:
    kind: str
    title: str
    reason: str
    retryable: bool
    status_code: int = 500


@dataclass(frozen=True)
class StreamRetryEvent:
    attempt: int
    max_attempts: int
    retry_after_ms: int

    def to_payload(self) -> dict[str, Any]:
        return {
            "attempt": self.attempt,
            "max_attempts": self.max_attempts,
            "retry_after_ms": self.retry_after_ms,
            "message": f"正在重试（{self.attempt}/{self.max_attempts}）",
        }


class StreamStageError(Exception):
    def __init__(self, error: Exception, *, stage: str, had_output: bool = False):
        self.error = error
        self.stage = stage
        self.had_output = had_output
        super().__init__(f"{stage} stream failed")


StreamItem = T | StreamRetryEvent


_STAGE_ERRORS: dict[str, StreamErrorInfo] = {
    "model": StreamErrorInfo("model", "模型调用失败", "模型服务暂时不可用，请稍后重试。", True),
    "retrieval": StreamErrorInfo("retrieval", "知识检索失败", "暂时无法检索相关知识，请稍后重试。", False),
    "document": StreamErrorInfo("document", "文档暂不可用", "文档可能尚未就绪或已失效，请稍后再试。", False),
    "auth": StreamErrorInfo("auth", "认证或权限失败", "当前账号无权执行此操作，请检查登录状态或权限。", False, 403),
    "config": StreamErrorInfo("config", "问答配置异常", "问答模型或服务尚未正确配置，请联系管理员。", False),
    "system": StreamErrorInfo("system", "问答服务异常", "问答服务暂时不可用，请稍后重试。", False),
}

_NETWORK_ERROR = StreamErrorInfo("network", "网络连接失败", "连接问答服务超时或中断，请稍后重试。", True, 502)
_RATE_LIMIT_ERROR = StreamErrorInfo("rate_limit", "请求过于频繁", "服务当前繁忙，请稍后重试。", True, 429)
_MODEL_REQUEST_ERROR = StreamErrorInfo(
    "model",
    "模型调用失败",
    "模型请求未被服务接受，请检查模型配置或输入。",
    False,
    400,
)

_AUTH_MARKERS = (
    "unauthorized",
    "forbidden",
    "authentication",
    "permission denied",
    "invalid api key",
    "invalid_api_key",
)
_CONFIG_MARKERS = (
    "not configured",
    "missing model",
    "model not found",
    "no llm",
    "configuration",
    "invalid parameter",
)
_NETWORK_MARKERS = (
    "timeout",
    "timed out",
    "connection reset",
    "connection refused",
    "connection error",
    "network error",
    "temporarily unavailable",
    "bad gateway",
    "service unavailable",
)


def _read_status_code(error: Exception) -> int | None:
    for source in (error, getattr(error, "response", None)):
        if source is None:
            continue
        for field in ("status_code", "status", "code"):
            raw = getattr(source, field, None)
            try:
                value = int(raw)
            except (TypeError, ValueError):
                continue
            if 100 <= value <= 599:
                return value
    return None


def classify_stream_error(error: Exception, *, stage: str = "system") -> StreamErrorInfo:
    status_code = _read_status_code(error)
    error_name = error.__class__.__name__.lower()
    error_text = str(error).lower()

    if status_code == 429 or "ratelimit" in error_name or "rate limit" in error_text:
        return _RATE_LIMIT_ERROR
    if stage == "rate_limit":
        return _RATE_LIMIT_ERROR
    if (
        status_code in {401, 403}
        or "permission" in error_name
        or "unauthorized" in error_name
        or any(marker in error_text for marker in _AUTH_MARKERS)
    ):
        return _STAGE_ERRORS["auth"]
    if isinstance(error, (TimeoutError, ConnectionError)) or any(
        marker in error_name or marker in error_text for marker in _NETWORK_MARKERS
    ):
        return _NETWORK_ERROR
    if status_code in {408, 502, 503, 504}:
        return _NETWORK_ERROR
    if stage == "config" or any(marker in error_text for marker in _CONFIG_MARKERS):
        return _STAGE_ERRORS["config"]
    if stage == "model" and status_code is not None and 400 <= status_code < 500:
        return _MODEL_REQUEST_ERROR
    return _STAGE_ERRORS.get(stage, _STAGE_ERRORS["system"])


def stream_error_payload(
    error: Exception,
    *,
    stage: str = "system",
    had_output: bool = False,
) -> dict[str, Any]:
    info = classify_stream_error(error, stage=stage)
    return {
        "status_code": info.status_code,
        "status_message": info.title,
        "data": {},
        "kind": info.kind,
        "title": info.title,
        "reason": info.reason,
        "retryable": info.retryable and not had_output,
    }


def stream_error_sse(
    error: Exception,
    *,
    stage: str = "system",
    had_output: bool = False,
) -> str:
    payload = stream_error_payload(error, stage=stage, had_output=had_output)
    return f"event: error\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def stream_retry_sse(event: StreamRetryEvent) -> str:
    return f"event: retry\ndata: {json.dumps(event.to_payload(), ensure_ascii=False)}\n\n"


async def retry_async_stream(
    stream_factory: Callable[[], AsyncIterator[T]],
    *,
    stage: str = "model",
    max_retries: int = 2,
    sleep: SleepCallable = asyncio.sleep,
    is_output: Callable[[T], bool] | None = None,
) -> AsyncIterator[StreamItem[T]]:
    retry_count = 0
    while True:
        emitted = False
        try:
            async for item in stream_factory():
                emitted = emitted or (is_output(item) if is_output else True)
                yield item
            return
        except Exception as error:
            info = classify_stream_error(error, stage=stage)
            if emitted or not info.retryable or retry_count >= max_retries:
                raise
            retry_count += 1
            delay_ms = min(500 * (2 ** (retry_count - 1)), 5000)
            yield StreamRetryEvent(
                attempt=retry_count,
                max_attempts=max_retries,
                retry_after_ms=delay_ms,
            )
            await sleep(delay_ms / 1000)
