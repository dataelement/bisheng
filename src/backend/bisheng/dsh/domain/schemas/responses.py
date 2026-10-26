"""Bounded stateless Responses subset. No remote files, stored conversations or hosted tools."""

import json
from typing import Annotated, Literal

from pydantic import Field, model_validator

from bisheng.dsh.domain.schemas.contracts import DshContract
from bisheng.dsh.domain.schemas.image import ImageUrl
from bisheng.dsh.domain.schemas.reasoning import EffortId

MAX_REQUEST_BYTES = 32 * 1024 * 1024
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
MAX_EVENT_BYTES = 8 * 1024 * 1024
ItemId = Annotated[str, Field(min_length=1, max_length=256, pattern=r"^[^\x00-\x20\x7f]+$")]


class InputText(DshContract):
    type: Literal["input_text"]
    text: str


class InputImage(DshContract):
    type: Literal["input_image"]
    image_url: str
    detail: Literal["auto", "low", "high"] = "auto"

    @model_validator(mode="after")
    def valid_image(self):
        ImageUrl(url=self.image_url, detail=self.detail)
        return self


class Citation(DshContract):
    type: Literal["url_citation"]
    url: str = Field(max_length=8192, pattern=r"^https?://")
    title: str
    start_index: int = Field(ge=0)
    end_index: int = Field(ge=0)


class OutputText(DshContract):
    type: Literal["output_text"]
    text: str
    annotations: list[Citation] = Field(default_factory=list)
    logprobs: None | list = None

    @model_validator(mode="after")
    def no_logprobs(self):
        if self.logprobs:
            raise ValueError("Logprobs are outside the negotiated subset")
        return self


class Refusal(DshContract):
    type: Literal["refusal"]
    refusal: str


Part = Annotated[InputText | InputImage | OutputText | Refusal, Field(discriminator="type")]


class Message(DshContract):
    type: Literal["message"] = "message"
    role: Literal["system", "developer", "user", "assistant"]
    content: str | list[Part]
    id: ItemId | None = None
    status: Literal["in_progress", "completed", "incomplete"] | None = None
    phase: Literal["commentary", "final_answer"] | None = None

    @model_validator(mode="after")
    def role_content(self):
        if isinstance(self.content, list):
            for part in self.content:
                if (part.type in {"output_text", "refusal"}) != (self.role == "assistant"):
                    raise ValueError("Invalid message content role")
        if self.phase is not None and self.role != "assistant":
            raise ValueError("Only assistant messages have phase")
        return self


class Summary(DshContract):
    type: Literal["summary_text"]
    text: str


class ReasoningText(DshContract):
    type: Literal["reasoning_text"]
    text: str


class ReasoningItem(DshContract):
    type: Literal["reasoning"]
    id: ItemId
    summary: list[Summary]
    encrypted_content: str | None = None
    content: list[ReasoningText] | None = None
    status: Literal["in_progress", "completed", "incomplete"] | None = None


class FunctionCall(DshContract):
    type: Literal["function_call"]
    call_id: ItemId
    name: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    arguments: str
    id: ItemId | None = None
    status: Literal["in_progress", "completed", "incomplete"] | None = None

    @model_validator(mode="after")
    def json_arguments(self):
        if not isinstance(json.loads(self.arguments), dict):
            raise ValueError("Tool arguments must be an object")
        return self


class FunctionResult(DshContract):
    type: Literal["function_call_output"]
    call_id: ItemId
    output: str | list[Annotated[InputText | InputImage, Field(discriminator="type")]]
    id: ItemId | None = None
    status: Literal["in_progress", "completed", "incomplete"] | None = None


InputItem = Annotated[Message | ReasoningItem | FunctionCall | FunctionResult, Field(discriminator="type")]


class FunctionTool(DshContract):
    type: Literal["function"]
    name: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    description: str | None = None
    parameters: dict
    strict: bool | None = None


class NamedTool(DshContract):
    type: Literal["function"]
    name: str


class ReasoningOptions(DshContract):
    effort: EffortId | None = None
    summary: Literal["auto", "concise", "detailed"] | None = None


class TextFormat(DshContract):
    type: Literal["text"] = "text"


class TextOptions(DshContract):
    format: TextFormat = Field(default_factory=TextFormat)
    verbosity: Literal["low", "medium", "high"] | None = None


class DshResponsesRequest(DshContract):
    model: str = Field(max_length=27, pattern=r"^bisheng:[1-9][0-9]*$")
    input: list[InputItem] = Field(min_length=1, max_length=4096)
    stream: bool = False
    store: Literal[False] = False
    include: list[Literal["reasoning.encrypted_content"]] = Field(
        default_factory=lambda: ["reasoning.encrypted_content"], max_length=1
    )
    tools: list[FunctionTool] | None = Field(default=None, max_length=128)
    tool_choice: Literal["auto", "none", "required"] | NamedTool | None = None
    parallel_tool_calls: bool | None = None
    max_output_tokens: int | None = Field(default=None, gt=0)
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, ge=0, le=1)
    reasoning: ReasoningOptions | None = None
    text: TextOptions | None = None

    @property
    def model_id(self) -> int:
        return int(self.model.removeprefix("bisheng:"))

    @model_validator(mode="before")
    @classmethod
    def easy_messages(cls, value):
        if isinstance(value, dict) and isinstance(value.get("input"), list):
            value = {
                **value,
                "input": [
                    {"type": "message", **item} if isinstance(item, dict) and "type" not in item else item
                    for item in value["input"]
                ],
            }
        return value

    @model_validator(mode="after")
    def semantics(self):
        if self.model_id > 9223372036854775807:
            raise ValueError("Model identifier is out of range")
        names = [tool.name for tool in self.tools or []]
        if len(names) != len(set(names)):
            raise ValueError("Tool names must be unique")
        if (self.tool_choice == "required" and not names) or (
            isinstance(self.tool_choice, NamedTool) and self.tool_choice.name not in names
        ):
            raise ValueError("Tool choice requires a declared tool")
        pending, seen = set(), set()
        image_size = 0
        for item in self.input:
            if isinstance(item, FunctionCall):
                if item.call_id in seen:
                    raise ValueError("Duplicate tool call")
                seen.add(item.call_id)
                pending.add(item.call_id)
            elif isinstance(item, FunctionResult):
                if item.call_id not in pending:
                    raise ValueError("Tool output has no pending call")
                pending.remove(item.call_id)
            elif isinstance(item, Message) and pending:
                raise ValueError("Tool output is required before continuing")
            blocks = (
                item.content if isinstance(item, Message) else item.output if isinstance(item, FunctionResult) else []
            )
            if isinstance(blocks, list):
                image_size += sum(len(part.image_url) for part in blocks if isinstance(part, InputImage))
        if pending or image_size > 28_000_000:
            raise ValueError("Unmatched tools or excessive images")
        # Total size is bounded while reading the body (MAX_REQUEST_BYTES).
        return self
