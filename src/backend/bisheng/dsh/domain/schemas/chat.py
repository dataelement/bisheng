"""Frozen DSH text/tool Chat Completions input; unknown fields are errors."""

import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bisheng.dsh.domain.schemas.contracts import DshContract

PositiveInt = Annotated[int, Field(strict=True, gt=0)]


class ChatCapabilities(BaseModel):
    """Protocol capabilities supplied by existing provider adapters to the chat contract."""

    model_config = ConfigDict(extra="forbid", strict=True)
    streaming: bool = Field(default=True, description="Whether the provider supports streamed chat responses.")
    tools: bool = Field(default=True, description="Whether the provider supports function tools and tool choice.")
    reasoning_content: bool = Field(
        default=False, description="Whether assistant reasoning content is supported by the provider."
    )
    max_completion_tokens: bool = Field(
        default=False, description="Whether the provider accepts max_completion_tokens instead of max_tokens."
    )
    stop: bool = Field(default=True, description="Whether the provider accepts stop sequences.")
    temperature: bool = Field(
        default=True, description="Whether the provider accepts a temperature sampling parameter."
    )
    top_p: bool = Field(default=True, description="Whether the provider accepts a top_p sampling parameter.")

    def client_fields(self) -> dict[str, bool]:
        return self.model_dump(include={"streaming", "tools", "reasoning_content"})


class ToolFunction(DshContract):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    description: str | None = None
    parameters: dict


class ChatTool(DshContract):
    type: Literal["function"]
    function: ToolFunction


class CalledFunction(DshContract):
    name: str = Field(min_length=1)
    arguments: str

    @model_validator(mode="after")
    def valid_json(self):
        json.loads(self.arguments)
        return self


class ToolCall(DshContract):
    id: str = Field(min_length=1)
    type: Literal["function"]
    function: CalledFunction


class ChatMessage(DshContract):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    reasoning_content: str | None = None

    @model_validator(mode="after")
    def role_fields(self):
        if self.role != "assistant" and (self.tool_calls is not None or self.reasoning_content is not None):
            raise ValueError("Only assistant messages carry calls or reasoning")
        if self.content is None and not (self.role == "assistant" and self.tool_calls):
            raise ValueError("Null content requires assistant tool calls")
        if (self.role == "tool") != (self.tool_call_id is not None):
            raise ValueError("Tool responses require their call ID")
        return self


class SelectedFunction(DshContract):
    name: str = Field(min_length=1)


class SelectedTool(DshContract):
    type: Literal["function"]
    function: SelectedFunction


class StreamOptions(DshContract):
    include_usage: bool

    @model_validator(mode="after")
    def enabled_usage(self):
        if self.include_usage is not True:
            raise ValueError("Only include_usage=true is supported")
        return self


class DshChatRequest(DshContract):
    model: str = Field(max_length=27, pattern=r"^bisheng:[1-9][0-9]*$")
    messages: list[ChatMessage] = Field(min_length=1)
    tools: list[ChatTool] | None = Field(default=None, min_length=1)
    tool_choice: Literal["auto", "none", "required"] | SelectedTool | None = None
    stream: bool = False
    stream_options: StreamOptions | None = None
    max_tokens: PositiveInt | None = None
    max_completion_tokens: PositiveInt | None = None
    temperature: Annotated[float, Field(strict=True, ge=0, le=2)] | None = None
    top_p: Annotated[float, Field(strict=True, ge=0, le=1)] | None = None
    stop: str | Annotated[list[str], Field(min_length=1, max_length=4)] | None = None
    n: Annotated[int, Field(strict=True, ge=1, le=1)] = 1

    @property
    def model_id(self) -> int:
        return int(self.model.removeprefix("bisheng:"))

    @model_validator(mode="after")
    def request_semantics(self):
        if self.model_id > 9223372036854775807:
            raise ValueError("Model identifier is out of range")
        if self.max_tokens is not None and self.max_completion_tokens is not None:
            raise ValueError("Output limits are mutually exclusive")
        if self.stream_options is not None and not self.stream:
            raise ValueError("stream_options requires stream=true")
        names = [tool.function.name for tool in self.tools or []]
        if len(names) != len(set(names)):
            raise ValueError("Tool names must be unique")
        if self.tool_choice == "required" and not names:
            raise ValueError("Required tool choice needs tools")
        if isinstance(self.tool_choice, SelectedTool) and self.tool_choice.function.name not in names:
            raise ValueError("Named tool choice must exist in tools")
        pending, seen = set(), set()
        for message in self.messages:
            if message.role == "tool":
                if message.tool_call_id not in pending:
                    raise ValueError("Tool response has no unmatched preceding call")
                pending.remove(message.tool_call_id)
            elif pending:
                raise ValueError("All tool calls require responses before continuing")
            for call in message.tool_calls or []:
                if call.id in seen:
                    raise ValueError("Tool call IDs must be unique")
                seen.add(call.id)
                pending.add(call.id)
        if pending:
            raise ValueError("Tool calls require matching results")
        return self
