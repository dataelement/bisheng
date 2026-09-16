"""OpenAI-shaped request / response bodies for the model protocol face (F051).

The request model is deliberately permissive (``extra="allow"``): AC-18 promises
a named set of conversation elements and says everything beyond it is forwarded
verbatim without a promise, so unknown keys land in ``model_extra`` and travel
on to the provider rather than being rejected.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

CHAT_COMPLETION_ID_PREFIX = "chatcmpl-"


def new_request_id() -> str:
    return f"{CHAT_COMPLETION_ID_PREFIX}{uuid.uuid4().hex}"


class StreamOptions(BaseModel):
    model_config = ConfigDict(extra="allow")

    include_usage: bool = False


class ChatCompletionRequest(BaseModel):
    """The promised subset of the OpenAI chat completion request."""

    model_config = ConfigDict(extra="allow")

    model: str = Field(min_length=1)
    messages: list[dict[str, Any]] = Field(min_length=1)
    stream: bool = False
    stream_options: StreamOptions | None = None
    # Sampling / shaping parameters forwarded untouched (AC-17: nothing here is
    # rewritten, and no platform prompt is injected).
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    max_completion_tokens: int | None = None
    stop: str | list[str] | None = None
    # ``n`` is the one enumerated field with a hard refusal: BishengLLM produces a
    # single candidate, so anything above 1 would silently under-deliver.
    n: int | None = None
    presence_penalty: float | None = None
    frequency_penalty: float | None = None
    seed: int | None = None
    response_format: dict[str, Any] | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: str | dict[str, Any] | None = None
    parallel_tool_calls: bool | None = None
    user: str | None = None

    def forwarded_kwargs(self) -> dict[str, Any]:
        """Parameters handed to the provider on top of the messages."""

        kwargs: dict[str, Any] = {}
        for name in (
            "top_p",
            "max_tokens",
            "max_completion_tokens",
            "stop",
            "presence_penalty",
            "frequency_penalty",
            "seed",
            "response_format",
            "parallel_tool_calls",
            "user",
        ):
            value = getattr(self, name)
            if value is not None:
                kwargs[name] = value
        # Unknown fields ride along untouched — promised as "forwarded, not
        # guaranteed" rather than dropped.
        for key, value in (self.model_extra or {}).items():
            kwargs.setdefault(key, value)
        return kwargs


class FunctionCall(BaseModel):
    name: str | None = None
    arguments: str = ""


class ToolCall(BaseModel):
    id: str | None = None
    type: str = "function"
    function: FunctionCall


class ChatCompletionMessage(BaseModel):
    role: str = "assistant"
    content: str | None = None
    # DeepSeek / Qwen thinking models put their chain in a separate key. Emitted
    # only when non-empty; official clients ignore what they do not know.
    reasoning_content: str | None = None
    tool_calls: list[ToolCall] | None = None


class ChatCompletionChoice(BaseModel):
    index: int = 0
    message: ChatCompletionMessage
    finish_reason: str | None = None


class Usage(BaseModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class ChatCompletionResponse(BaseModel):
    id: str = Field(default_factory=new_request_id)
    object: Literal["chat.completion"] = "chat.completion"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str
    choices: list[ChatCompletionChoice]
    usage: Usage | None = None


class ToolCallDelta(BaseModel):
    index: int
    id: str | None = None
    type: str = "function"
    function: FunctionCall


class ChatCompletionDelta(BaseModel):
    role: str | None = None
    content: str | None = None
    reasoning_content: str | None = None
    tool_calls: list[ToolCallDelta] | None = None


class ChatCompletionChunkChoice(BaseModel):
    index: int = 0
    delta: ChatCompletionDelta
    finish_reason: str | None = None


class ChatCompletionChunk(BaseModel):
    id: str
    object: Literal["chat.completion.chunk"] = "chat.completion.chunk"
    created: int
    model: str
    choices: list[ChatCompletionChunkChoice]
    usage: Usage | None = None


class ModelObject(BaseModel):
    id: str
    object: Literal["model"] = "model"
    created: int
    owned_by: str
    bisheng_model_type: str = "llm"
    bisheng_qualified_name: str


class ModelList(BaseModel):
    object: Literal["list"] = "list"
    data: list[ModelObject]


class OpenAIError(BaseModel):
    message: str
    type: str
    code: str
    param: str | None = None
    # Extension key outside the OpenAI shape: official clients ignore it, our
    # own scripts classify on it exactly.
    bisheng_code: int | None = None
    candidates: list[str] | None = None


class OpenAIErrorBody(BaseModel):
    error: OpenAIError


__all__ = [
    "CHAT_COMPLETION_ID_PREFIX",
    "ChatCompletionChoice",
    "ChatCompletionChunk",
    "ChatCompletionChunkChoice",
    "ChatCompletionDelta",
    "ChatCompletionMessage",
    "ChatCompletionRequest",
    "ChatCompletionResponse",
    "FunctionCall",
    "ModelList",
    "ModelObject",
    "OpenAIError",
    "OpenAIErrorBody",
    "StreamOptions",
    "ToolCall",
    "ToolCallDelta",
    "Usage",
    "new_request_id",
]
