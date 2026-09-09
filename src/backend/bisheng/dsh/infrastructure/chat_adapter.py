"""Adapt text/tools through BishengLLM's public governed execution methods."""

from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import ValidationError

from bisheng.common.errcode.dsh import DshInvalidRequestError, DshUnsupportedParameterError, DshUpstreamErrorError
from bisheng.dsh.domain.schemas.chat import ChatCapabilities, DshChatRequest, SelectedTool, ToolCall
from bisheng.dsh.domain.schemas.contracts import DshTokenUsage

FINISH_REASONS = {"stop", "length", "tool_calls", "content_filter"}


def normalize_usage(message) -> DshTokenUsage:
    usage = getattr(message, "usage_metadata", None)
    if not usage:
        raw = getattr(message, "response_metadata", {}).get("token_usage") or {}
        usage = {
            "input_tokens": raw.get("prompt_tokens"),
            "output_tokens": raw.get("completion_tokens"),
            "total_tokens": raw.get("total_tokens"),
        }
    try:
        return DshTokenUsage.model_validate(
            {key: usage.get(key) for key in ("input_tokens", "output_tokens", "total_tokens")}
        )
    except (ValidationError, AttributeError):
        return DshTokenUsage()


class ChatExecution:
    def __init__(self, llm, messages: list, parameters: dict, capabilities: ChatCapabilities):
        self.llm, self.messages, self.parameters, self.capabilities = llm, messages, parameters, capabilities
        self.usage = DshTokenUsage()
        self.finish_reason: str | None = None
        self.provider_request_id: str | None = None
        self.tool_fragments: dict[int, dict] = {}
        self.allowed_tool_names: set[str] = set()

    def _observe(self, message):
        current = normalize_usage(message)
        if (
            getattr(message, "usage_metadata", None) is not None
            or getattr(message, "response_metadata", {}).get("token_usage") is not None
        ):
            self.usage = current
        metadata = getattr(message, "response_metadata", {})
        finish = metadata.get("finish_reason") or metadata.get("stop_reason")
        if finish is not None:
            if finish not in FINISH_REASONS:
                raise DshUpstreamErrorError()
            self.finish_reason = finish
        self.provider_request_id = getattr(message, "id", None) or self.provider_request_id

    def _reasoning(self, message, output):
        reasoning = getattr(message, "additional_kwargs", {}).get("reasoning_content")
        if reasoning is not None:
            if not self.capabilities.reasoning_content or not isinstance(reasoning, str):
                raise DshUpstreamErrorError()
            output["reasoning_content"] = reasoning

    async def invoke(self) -> dict:
        message = await self.llm.ainvoke(self.messages, **self.parameters)
        self._observe(message)
        if not isinstance(message.content, str):
            raise DshUpstreamErrorError()
        output: dict[str, Any] = {"role": "assistant", "content": message.content}
        calls = getattr(message, "additional_kwargs", {}).get("tool_calls")
        if calls:
            output["tool_calls"] = calls
            if not message.content:
                output["content"] = None
        elif getattr(message, "tool_calls", None):
            import json

            output["tool_calls"] = [
                {
                    "id": call["id"],
                    "type": "function",
                    "function": {
                        "name": call["name"],
                        "arguments": json.dumps(call["args"], ensure_ascii=False, separators=(",", ":")),
                    },
                }
                for call in message.tool_calls
            ]
        self._reasoning(message, output)
        self._validate_calls(output.get("tool_calls", []))
        if self.finish_reason is None:
            raise DshUpstreamErrorError()
        return {"message": output, "finish_reason": self.finish_reason}

    def _validate_calls(self, calls: list[dict]):
        if self.finish_reason == "tool_calls" and not calls:
            raise DshUpstreamErrorError()
        if calls and self.finish_reason != "tool_calls":
            raise DshUpstreamErrorError()
        ids = set()
        for raw in calls:
            try:
                call = ToolCall.model_validate(raw)
            except ValidationError as exc:
                raise DshUpstreamErrorError() from exc
            if call.id in ids or call.function.name not in self.allowed_tool_names:
                raise DshUpstreamErrorError()
            ids.add(call.id)

    async def stream(self) -> AsyncIterator[dict]:
        source = self.llm.astream(self.messages, **self.parameters)
        try:
            async for message in source:
                self._observe(message)
                delta: dict[str, Any] = {}
                if message.content:
                    if not isinstance(message.content, str):
                        raise DshUpstreamErrorError()
                    delta["content"] = message.content
                calls = getattr(message, "tool_call_chunks", None)
                if calls:
                    delta["tool_calls"] = []
                    for call in calls:
                        index = call.get("index")
                        if type(index) is not int or index < 0:
                            raise DshUpstreamErrorError()
                        saved = self.tool_fragments.setdefault(
                            index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
                        )
                        if call.get("id"):
                            if saved["id"] and saved["id"] != call["id"]:
                                raise DshUpstreamErrorError()
                            saved["id"] = call["id"]
                        saved["function"]["name"] += call.get("name") or ""
                        saved["function"]["arguments"] += call.get("args") or ""
                        piece = {"index": index, "function": {"arguments": call.get("args") or ""}}
                        if call.get("id"):
                            piece.update(id=call["id"], type="function")
                        if call.get("name"):
                            piece["function"]["name"] = call["name"]
                        delta["tool_calls"].append(piece)
                self._reasoning(message, delta)
                if delta:
                    yield delta
        finally:
            if hasattr(source, "aclose"):
                await source.aclose()
        if self.finish_reason is None:
            raise DshUpstreamErrorError()
        self._validate_calls(list(self.tool_fragments.values()))


class DshChatAdapter:
    def prepare(
        self, request: DshChatRequest, llm, capabilities: ChatCapabilities, *, max_output_tokens: int | None = None
    ):
        if (request.stream and not capabilities.streaming) or (request.tools and not capabilities.tools):
            raise DshUnsupportedParameterError()
        for field in ("max_completion_tokens", "stop", "temperature", "top_p"):
            if getattr(request, field) is not None and not getattr(capabilities, field):
                raise DshUnsupportedParameterError()
        output_limit = request.max_tokens or request.max_completion_tokens
        if max_output_tokens is not None and output_limit is not None and output_limit > max_output_tokens:
            raise DshInvalidRequestError()
        messages = []
        for item in request.messages:
            extras = {}
            if item.reasoning_content is not None:
                if not capabilities.reasoning_content:
                    raise DshUnsupportedParameterError()
                extras["reasoning_content"] = item.reasoning_content
            if item.tool_calls:
                extras["tool_calls"] = [call.model_dump() for call in item.tool_calls]
            if item.role == "tool":
                message = ToolMessage(content=item.content, tool_call_id=item.tool_call_id)
            else:
                message_type = {"user": HumanMessage, "system": SystemMessage, "assistant": AIMessage}[item.role]
                message = message_type(content=item.content or "", additional_kwargs=extras)
            messages.append(message)
        parameters = {
            key: getattr(request, key)
            for key in ("max_tokens", "max_completion_tokens", "temperature", "top_p", "stop")
            if getattr(request, key) is not None
        }
        if request.tools:
            choice = request.tool_choice or "auto"
            if isinstance(choice, SelectedTool):
                choice = choice.model_dump()
            llm = llm.bind_tools([tool.model_dump(exclude_none=True) for tool in request.tools], tool_choice=choice)
        elif request.tool_choice not in {None, "none"}:
            raise DshUnsupportedParameterError()
        execution = ChatExecution(llm, messages, parameters, capabilities)
        execution.allowed_tool_names = {tool.function.name for tool in request.tools or []}
        return execution
