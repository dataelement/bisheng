"""Translation between the OpenAI wire shapes and langchain objects (F051 D8).

Pure functions and one small assembler — no database, no settings, no HTTP. The
face's request path is thin on purpose so the fiddly parts (tool-call indices,
usage, upstream error classification) are unit-testable without a model.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.messages.utils import convert_to_messages

from bisheng.common.errcode.model_face import (
    ModelFaceError,
    ModelFaceRequestInvalidError,
    ModelFaceStreamInterruptedError,
    ModelFaceUpstreamError,
    ModelFaceUpstreamRateLimitedError,
    ModelFaceUpstreamRejectedError,
)
from bisheng.llm.domain.utils import extract_reasoning_content, get_token_from_usage
from bisheng.open_api.domain.schemas.model_gateway import (
    ChatCompletionChoice,
    ChatCompletionChunk,
    ChatCompletionChunkChoice,
    ChatCompletionDelta,
    ChatCompletionMessage,
    ChatCompletionResponse,
    FunctionCall,
    ToolCall,
    ToolCallDelta,
    Usage,
)

SSE_DONE = "data: [DONE]\n\n"

# Anything shaped like a key gets scrubbed before it reaches a response body or
# a log line: provider SDKs are entirely willing to echo the credential back
# inside an exception message.
_SECRET_PATTERNS = (
    re.compile(r"\b(?:bs-sak-|bs-pat-)[A-Za-z0-9_\-]+"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]+"),
)
_REDACTED = "[redacted]"

UPSTREAM_MESSAGE_MAX_CHARS = 500


def redact_secrets(text: str) -> str:
    result = text
    for pattern in _SECRET_PATTERNS:
        result = pattern.sub(_REDACTED, result)
    return result


def to_langchain_messages(messages: list[dict[str, Any]]) -> list[BaseMessage]:
    """Convert OpenAI messages verbatim — no prompt is added or rewritten."""

    try:
        return convert_to_messages(messages)
    except Exception as exc:
        raise ModelFaceRequestInvalidError(exception=exc, msg=redact_secrets(str(exc))) from exc


def _content_text(content: Any) -> str | None:
    if content is None:
        return None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts)
    return str(content)


def _tool_calls_of(message: AIMessage) -> list[ToolCall]:
    calls = []
    for index, call in enumerate(getattr(message, "tool_calls", None) or []):
        arguments = call.get("args")
        calls.append(
            ToolCall(
                id=call.get("id") or f"call_{index}",
                type="function",
                function=FunctionCall(
                    name=call.get("name"),
                    # OpenAI carries arguments as a JSON *string*; langchain
                    # parses them into a dict, so put them back.
                    arguments=json.dumps(arguments, ensure_ascii=False) if arguments is not None else "",
                ),
            )
        )
    return calls


def usage_from(result: Any) -> Usage | None:
    """Token counts off the same object the platform telemetry reads.

    ``None`` when upstream said nothing — which is not zero (AC-23). The
    telemetry ledger has no "unknown" and records 0 there; this is the one
    deliberate difference between the two, and it is here rather than in the
    telemetry so the existing ledger keeps its shape.
    """

    if result is None:
        return None
    message = getattr(result, "message", result)
    response_metadata = getattr(message, "response_metadata", None) or {}
    token_usage = response_metadata.get("token_usage") or getattr(message, "usage_metadata", None)
    input_token, output_token, _cache_token, total_token = get_token_from_usage(token_usage)
    if not input_token and not output_token and not total_token:
        return None
    return Usage(
        prompt_tokens=input_token,
        completion_tokens=output_token,
        total_tokens=total_token or (input_token + output_token),
    )


def build_completion(message: AIMessage, *, model: str, request_id: str) -> ChatCompletionResponse:
    tool_calls = _tool_calls_of(message)
    reasoning = extract_reasoning_content(message) or None
    response_metadata = getattr(message, "response_metadata", None) or {}
    finish_reason = response_metadata.get("finish_reason") or ("tool_calls" if tool_calls else "stop")
    return ChatCompletionResponse(
        id=request_id,
        created=int(time.time()),
        model=model,
        choices=[
            ChatCompletionChoice(
                index=0,
                message=ChatCompletionMessage(
                    role="assistant",
                    content=_content_text(message.content) or "",
                    reasoning_content=reasoning,
                    tool_calls=tool_calls or None,
                ),
                finish_reason=finish_reason,
            )
        ],
        usage=usage_from(message),
    )


def sse_line(payload: Any) -> str:
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(exclude_none=True)
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


class ChunkAssembler:
    """Turns langchain chunks into OpenAI ``chat.completion.chunk`` lines.

    The tool-call ``index`` is assigned here rather than forwarded. Several
    providers (qwen, zhipu through their own SDKs) deliver ``index=None`` and
    only put the call ``id`` on the first chunk; forwarding that verbatim makes
    a client concatenate two parallel tool calls' arguments into one.
    """

    def __init__(self, *, model: str, request_id: str) -> None:
        self.model = model
        self.request_id = request_id
        self.created = int(time.time())
        self.last_chunk: Any = None
        self.saw_tool_call = False
        self._tool_index: dict[Any, int] = {}
        self._last_tool_key: Any = None
        self._sent_role = False

    def _chunk(self, delta: ChatCompletionDelta, finish_reason: str | None = None) -> ChatCompletionChunk:
        return ChatCompletionChunk(
            id=self.request_id,
            created=self.created,
            model=self.model,
            choices=[ChatCompletionChunkChoice(index=0, delta=delta, finish_reason=finish_reason)],
        )

    def role_prelude(self) -> str:
        self._sent_role = True
        return sse_line(self._chunk(ChatCompletionDelta(role="assistant", content="")))

    def _resolve_tool_index(self, call: dict[str, Any]) -> int:
        call_id = call.get("id")
        raw_index = call.get("index")
        if call_id:
            key: Any = ("id", call_id)
        elif raw_index is not None:
            key = ("index", raw_index)
        elif self._last_tool_key is not None:
            # A continuation fragment of the call we are already assembling.
            key = self._last_tool_key
        else:
            key = ("position", 0)
        if key not in self._tool_index:
            self._tool_index[key] = len(self._tool_index)
        self._last_tool_key = key
        return self._tool_index[key]

    def next(self, chunk: Any) -> str | None:
        """Render one upstream chunk, or ``None`` when it carries nothing."""

        self.last_chunk = chunk
        message = getattr(chunk, "message", chunk)
        delta = ChatCompletionDelta()
        emitted = False

        content = _content_text(getattr(message, "content", None))
        if content:
            delta.content = content
            emitted = True

        reasoning = extract_reasoning_content(message)
        if reasoning:
            delta.reasoning_content = reasoning
            emitted = True

        tool_call_chunks = getattr(message, "tool_call_chunks", None) or []
        tool_deltas = []
        for call in tool_call_chunks:
            index = self._resolve_tool_index(call)
            tool_deltas.append(
                ToolCallDelta(
                    index=index,
                    id=call.get("id"),
                    type="function",
                    function=FunctionCall(name=call.get("name"), arguments=call.get("args") or ""),
                )
            )
        if tool_deltas:
            delta.tool_calls = tool_deltas
            self.saw_tool_call = True
            emitted = True

        if not emitted:
            return None
        if not self._sent_role:
            delta.role = "assistant"
            self._sent_role = True
        return sse_line(self._chunk(delta))

    def finish(self) -> str:
        message = getattr(self.last_chunk, "message", self.last_chunk)
        response_metadata = getattr(message, "response_metadata", None) or {}
        finish_reason = response_metadata.get("finish_reason") or ("tool_calls" if self.saw_tool_call else "stop")
        return sse_line(self._chunk(ChatCompletionDelta(), finish_reason=finish_reason))

    def usage(self, *, include_usage: bool) -> str | None:
        if not include_usage:
            return None
        usage = usage_from(self.last_chunk)
        if usage is None:
            return None
        payload = ChatCompletionChunk(
            id=self.request_id,
            created=self.created,
            model=self.model,
            choices=[],
            usage=usage,
        )
        return sse_line(payload)

    @staticmethod
    def error(exc: ModelFaceError) -> str:
        return sse_line(
            {
                "error": {
                    "message": redact_secrets(str(exc) or exc.message),
                    "type": exc.openai_type,
                    "code": exc.openai_code,
                    "param": None,
                    "bisheng_code": exc.code,
                }
            }
        )


def classify_upstream_error(exc: Exception) -> ModelFaceError:
    """Map a provider SDK failure onto the 262 upstream band.

    An unrecognised exception becomes 26231 with a truncated, scrubbed message
    rather than a bare 5xx string — an agent needs something it can read.
    """

    if isinstance(exc, ModelFaceError):
        return exc

    status = getattr(exc, "status_code", None)
    raw_message = getattr(exc, "message", None) or str(exc)
    message = redact_secrets(str(raw_message))[:UPSTREAM_MESSAGE_MAX_CHARS]

    if isinstance(status, int):
        if status == 429:
            return ModelFaceUpstreamRateLimitedError(msg=message)
        if 400 <= status < 500:
            # The provider's own status travels outward: "context too long" is
            # a 413 whichever side of the proxy you stand on.
            return ModelFaceUpstreamRejectedError(msg=message, http_status=status)
    return ModelFaceUpstreamError(msg=message)


def classify_stream_error(exc: Exception) -> ModelFaceError:
    """Same mapping, but an unrecognised failure mid-stream is 26234."""

    if isinstance(exc, ModelFaceError):
        return exc
    if getattr(exc, "status_code", None) is not None:
        return classify_upstream_error(exc)
    return ModelFaceStreamInterruptedError(msg=redact_secrets(str(exc))[:UPSTREAM_MESSAGE_MAX_CHARS])


__all__ = [
    "SSE_DONE",
    "UPSTREAM_MESSAGE_MAX_CHARS",
    "ChunkAssembler",
    "build_completion",
    "classify_stream_error",
    "classify_upstream_error",
    "redact_secrets",
    "sse_line",
    "to_langchain_messages",
    "usage_from",
]
