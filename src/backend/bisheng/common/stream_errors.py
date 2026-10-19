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
# 这三类是供应商拒绝, 不是用户登录失败, 也不能靠原样重试消除.
_MODEL_INPUT_TOO_LONG = StreamErrorInfo(
    "model",
    "内容超出模型长度",
    "这次提问和附带内容超过了当前模型能接受的长度。请缩短提问或减少附带内容；若经常出现，请管理员更换可接受更长内容的模型。",
    False,
    400,
)
_MODEL_NOT_FOUND = StreamErrorInfo(
    "model",
    "当前模型不可用",
    "当前选用的模型在服务商侧不存在或已下线。请管理员在模型管理中改成可用模型后再试。",
    False,
    404,
)
_MODEL_ACCESS_DENIED = StreamErrorInfo(
    "model",
    "模型没有调用权限",
    "当前模型没有调用权限，这次回答无法继续。请管理员检查该模型的开通状态和密钥权限。",
    False,
    403,
)
_UNKNOWN_MODEL_REJECTION = StreamErrorInfo(
    "model",
    "模型请求被拒绝",
    "这次模型请求被拒绝，暂时无法判断具体原因。",
    False,
)

_INPUT_TOO_LONG_MARKERS = (
    "range of input length",
    "input length should be",
    "context length",
    "context_length_exceeded",
    "maximum context length",
    "prompt is too long",
    "prompt too long",
    "input is too long",
    "reduce the length",
)
_MODEL_NOT_FOUND_MARKERS = (
    "model not found",
    "model_not_found",
    "model not exist",
    "model_not_exist",
    "model does not exist",
)
_MODEL_ACCESS_DENIED_MARKERS = (
    "access denied",
    "access_denied",
    "invalid api key",
    "invalid_api_key",
    "invalid api-key",
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


def _matches_any(error_text: str, markers: tuple[str, ...]) -> bool:
    """判断异常原文是否命中任一口语片段.

    Args:
        error_text: 已转成小写的异常说明.
        markers: 供应商报错里稳定出现的英文片段.

    Returns:
        命中任一片段时为 True.
    """
    return any(marker in error_text for marker in markers)


def _safe_trace_id() -> str:
    """读取当前请求追踪号, 只保留能放进对话的短标识.

    Returns:
        由字母、数字、下划线或短横线组成的追踪号. 没有或含空格、斜杠时返回空字符串.
    """
    from bisheng.core.logger import trace_id_var

    raw = trace_id_var.get()
    if not isinstance(raw, str):
        return ""
    trace_id = raw.strip()
    if not trace_id or len(trace_id) > 64:
        return ""
    if any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in trace_id):
        return ""
    return trace_id


def classify_stream_error(error: Exception, *, stage: str = "system") -> StreamErrorInfo:
    """把流式问答异常收成可展示的原因.

    模型供应商的超长、不存在、无权限要先于账号权限和配置判断, 避免把密钥 403 说成用户未登录.
    模型阶段对不上已知原因时不再自动重试.

    Args:
        error: 调用链抛出的原始异常.
        stage: 失败时所在阶段, 如 model、retrieval.

    Returns:
        对话气泡使用的标题、原因和是否可重试.
    """
    status_code = _read_status_code(error)
    error_name = error.__class__.__name__.lower()
    error_text = str(error).lower()

    if status_code == 429 or "ratelimit" in error_name or "rate limit" in error_text:
        return _RATE_LIMIT_ERROR
    if stage == "rate_limit":
        return _RATE_LIMIT_ERROR
    if _matches_any(error_text, _INPUT_TOO_LONG_MARKERS):
        return _MODEL_INPUT_TOO_LONG
    if _matches_any(error_text, _MODEL_NOT_FOUND_MARKERS):
        return _MODEL_NOT_FOUND
    if _matches_any(error_text, _MODEL_ACCESS_DENIED_MARKERS):
        return _MODEL_ACCESS_DENIED
    # 模型调用上的 401/403 是供应商拒绝这个模型, 不是门户登录态失效.
    if stage == "model" and status_code in {401, 403}:
        return _MODEL_ACCESS_DENIED
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
    if stage == "model":
        return _UNKNOWN_MODEL_REJECTION
    return _STAGE_ERRORS.get(stage, _STAGE_ERRORS["system"])


def stream_error_payload(
    error: Exception,
    *,
    stage: str = "system",
    had_output: bool = False,
) -> dict[str, Any]:
    from bisheng.common.errcode.attachment import AttachmentQuestionError

    if isinstance(error, AttachmentQuestionError):
        return {
            "status_code": error.Code,
            "status_message": error.Msg,
            "data": {},
            "kind": "document",
            "title": error.Msg,
            "reason": "请处理问题附件后重新提问。",
            "retryable": False,
            "attachment_errors": error.attachment_errors,
        }
    info = classify_stream_error(error, stage=stage)
    reason = info.reason
    trace_id = _safe_trace_id() if info is _UNKNOWN_MODEL_REJECTION else ""
    if trace_id:
        reason = f"{reason}追踪号：{trace_id}。"
    return {
        "status_code": info.status_code,
        "status_message": info.title,
        "data": {},
        "kind": info.kind,
        "title": info.title,
        "reason": reason,
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
