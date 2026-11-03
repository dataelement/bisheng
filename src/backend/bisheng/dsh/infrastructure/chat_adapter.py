"""Adapt text/tools through BishengLLM's public governed execution methods."""

import asyncio
import json
import re
import traceback
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage, ToolMessage
from loguru import logger
from pydantic import ValidationError

from bisheng.common.errcode.dsh import DshInvalidRequestError, DshUnsupportedParameterError, DshUpstreamErrorError
from bisheng.dsh.domain.schemas.chat import ChatCapabilities, DshChatRequest, SelectedTool, ToolCall
from bisheng.dsh.domain.schemas.contracts import DshTokenUsage

FINISH_REASONS = {"stop", "length", "tool_calls", "content_filter"}


def normalize_usage(message) -> DshTokenUsage:
    usage = getattr(message, "usage_metadata", None)
    raw = getattr(message, "response_metadata", {}).get("token_usage") or {}
    raw = raw if isinstance(raw, dict) else {}
    if not usage:
        usage = {
            "input_tokens": raw.get("prompt_tokens"),
            "output_tokens": raw.get("completion_tokens"),
            "total_tokens": raw.get("total_tokens"),
        }
    try:
        normalized = DshTokenUsage.model_validate(
            {key: usage.get(key) for key in ("input_tokens", "output_tokens", "total_tokens")}
        )
    except (ValidationError, AttributeError):
        normalized = DshTokenUsage()
    details = usage.get("input_token_details") if isinstance(usage, dict) else None
    details = details if isinstance(details, dict) else {}
    raw_details = raw.get("prompt_tokens_details") if isinstance(raw, dict) else None
    raw_details = raw_details if isinstance(raw_details, dict) else {}

    def measured(*values):
        # Missing or malformed optional detail must not invalidate reliable totals.
        return next((value for value in values if type(value) is int and 0 <= value <= 9223372036854775807), None)

    normalized.cache_read_tokens = measured(
        details.get("cache_read"),
        raw_details.get("cached_tokens"),
        raw.get("cache_read_input_tokens"),
        raw.get("prompt_cache_hit_tokens"),
    )
    normalized.cache_creation_tokens = measured(
        details.get("cache_creation"),
        raw_details.get("cache_creation_tokens"),
        raw.get("cache_creation_input_tokens"),
    )
    return normalized


def accumulate_usage(previous: DshTokenUsage, message) -> DshTokenUsage:
    """LangChain streaming usage chunks are additive; ordinary results are totals."""
    current = normalize_usage(message)
    if current.total_tokens is None:
        return previous
    if not isinstance(message, AIMessageChunk) or previous.total_tokens is None:
        return current
    values = {}
    for name in DshTokenUsage.model_fields:
        old, new = getattr(previous, name), getattr(current, name)
        values[name] = None if old is None and new is None else (old or 0) + (new or 0)
    return DshTokenUsage.model_validate(values)


class ChatExecution:
    def __init__(self, llm, messages: list, parameters: dict, capabilities: ChatCapabilities):
        self.llm, self.messages, self.parameters, self.capabilities = llm, messages, parameters, capabilities
        self.usage = DshTokenUsage()
        self.finish_reason: str | None = None
        self.provider_request_id: str | None = None
        self.tool_fragments: dict[int, dict] = {}
        self.allowed_tool_names: set[str] = set()
        self.capture = None
        self.audit_input = None
        self.protocol_failure: str | None = None
        self.repair_tool_choice: str | dict | None = "required"
        self.last_output: dict | None = None

    def _protocol_error(self, reason: str):
        self.protocol_failure = reason
        # Only local diagnostic labels and counts belong in operational logs.
        logger.warning(
            "DSH chat protocol rejected response reason={} finish_reason={} tool_calls={}",
            reason,
            self.finish_reason,
            len(self.tool_fragments),
        )
        return DshUpstreamErrorError()

    def _log_failure(self, error):
        frames = traceback.extract_tb(error.__traceback__)
        frame = frames[-1] if frames else None
        logger.warning(
            "DSH chat execution failed exception_type={} function={} line={} finish_reason={} tool_calls={}",
            type(error).__name__,
            frame.name if frame else None,
            frame.lineno if frame else None,
            self.finish_reason,
            len(self.tool_fragments),
        )

    def audit(self, method, value):
        if self.capture is not None:
            try:
                getattr(self.capture, method)(value)
            except Exception as error:
                # Audit observers cannot alter unified model execution or its response.
                logger.warning("DSH audit observer failed ({})", type(error).__name__)

    def input_units(self):
        request = self.audit_input
        if request is None:
            return
        yield {
            "parameters": {
                key: value
                for key in type(request).model_fields
                if key not in {"messages", "tools", "tool_choice"}
                if (value := getattr(request, key)) is not None
            },
            "tools": request.tools or [],
            "tool_choice": request.tool_choice,
        }
        yield from request.messages

    def _observe(self, message):
        self.usage = accumulate_usage(self.usage, message)
        metadata = getattr(message, "response_metadata", {})
        finish = metadata.get("finish_reason") or metadata.get("stop_reason")
        if finish is not None:
            if finish not in FINISH_REASONS:
                raise self._protocol_error("unsupported_finish_reason")
            self.finish_reason = finish
        self.provider_request_id = getattr(message, "id", None) or self.provider_request_id

    def _reasoning(self, message, output):
        reasoning = getattr(message, "additional_kwargs", {}).get("reasoning_content")
        if reasoning is not None:
            if not self.capabilities.reasoning_content or not isinstance(reasoning, str):
                raise self._protocol_error("invalid_reasoning_content")
            output["reasoning_content"] = reasoning

    async def invoke(self) -> dict:
        self.audit("entered", self.input_units())
        try:
            result = (
                await self._buffered_tools()
                if self.allowed_tool_names and not self.capabilities.tool_streaming
                else await self._invoke()
            )
            self.audit("output", result)
            self.audit("terminal", "SUCCEEDED")
            return result
        except asyncio.CancelledError:
            self.audit("terminal", "CANCELLED")
            raise
        except Exception as error:
            self._log_failure(error)
            self.audit("terminal", "FAILED")
            raise

    async def _invoke(self) -> dict:
        message = await self.llm.ainvoke(self.messages, **self.parameters)
        self._observe(message)
        if not isinstance(message.content, str):
            raise self._protocol_error("invalid_content")
        output: dict[str, Any] = {"role": "assistant", "content": message.content}
        calls = getattr(message, "additional_kwargs", {}).get("tool_calls")
        if calls:
            output["tool_calls"] = calls
            if not message.content:
                output["content"] = None
        elif getattr(message, "tool_calls", None):
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
        if not calls:
            # LangChain moves malformed JSON to invalid_tool_calls; retain the
            # original fragments for validation, never execute or repair them.
            invalid = getattr(message, "invalid_tool_calls", None)
            if invalid:
                output.setdefault("tool_calls", []).extend(
                    {
                        "id": call.get("id"),
                        "type": "function",
                        "function": {
                            "name": call.get("name"),
                            "arguments": call.get("args"),
                        },
                    }
                    for call in invalid
                )
        self._reasoning(message, output)
        self.last_output = output
        if self.allowed_tool_names and not self.capabilities.tool_streaming and not output.get("tool_calls"):
            # M2.7 can report stop while leaking an unparsed tool invocation.
            visible = re.sub(r"<think>.*?</think>", "", message.content, flags=re.DOTALL).lstrip()
            visible = re.sub(r"```.*?```|`[^`]*`", "", visible, flags=re.DOTALL)
            if re.search(r"<(?:minimax:)?tool_call\s*>", visible):
                raise self._protocol_error("unparsed_tool_call")
        self._validate_calls(output.get("tool_calls", []))
        if self.finish_reason is None:
            raise self._protocol_error("missing_finish_reason")
        return {"message": output, "finish_reason": self.finish_reason}

    def _validate_calls(self, calls: list[dict]):
        if self.finish_reason == "tool_calls" and not calls:
            raise self._protocol_error("missing_tool_calls")
        if calls and self.finish_reason != "tool_calls":
            raise self._protocol_error("tool_finish_mismatch")
        ids = set()
        for raw in calls:
            try:
                call = ToolCall.model_validate(raw)
            except ValidationError as exc:
                arguments_error = any(
                    isinstance(error.get("ctx", {}).get("error"), json.JSONDecodeError)
                    for error in exc.errors(include_input=False)
                )
                raise self._protocol_error(
                    "invalid_tool_arguments" if arguments_error else "invalid_tool_call"
                ) from exc
            if call.id in ids or call.function.name not in self.allowed_tool_names:
                raise self._protocol_error("duplicate_or_unknown_tool")
            ids.add(call.id)

    async def stream(self) -> AsyncIterator[dict]:
        self.audit("entered", self.input_units())
        source = self._stream()
        try:
            async for delta in source:
                self.audit("output", {"delta": delta})
                yield delta
            self.audit("output", {"finish_reason": self.finish_reason})
            self.audit("terminal", "SUCCEEDED")
        except (asyncio.CancelledError, GeneratorExit):
            self.audit("terminal", "CANCELLED")
            raise
        except Exception as error:
            self._log_failure(error)
            self.audit("terminal", "FAILED")
            raise
        finally:
            await source.aclose()

    async def _stream(self) -> AsyncIterator[dict]:
        if self.allowed_tool_names and not self.capabilities.tool_streaming:
            # Validate a complete response before exposing any tool arguments.
            result = await self._buffered_tools()
            delta = {key: value for key, value in result["message"].items() if key != "role" and value is not None}
            if "tool_calls" in delta:
                delta["tool_calls"] = [{"index": index, **call} for index, call in enumerate(delta["tool_calls"])]
            yield delta
            return
        source = self.llm.astream(self.messages, **self.parameters)
        try:
            async for message in source:
                self._observe(message)
                delta: dict[str, Any] = {}
                if message.content:
                    if not isinstance(message.content, str):
                        raise self._protocol_error("invalid_content")
                    delta["content"] = message.content
                calls = getattr(message, "tool_call_chunks", None)
                if calls:
                    delta["tool_calls"] = []
                    for call in calls:
                        index = call.get("index")
                        if type(index) is not int or index < 0:
                            raise self._protocol_error("invalid_tool_index")
                        saved = self.tool_fragments.setdefault(
                            index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
                        )
                        if call.get("id"):
                            if saved["id"] and saved["id"] != call["id"]:
                                raise self._protocol_error("changed_tool_id")
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
            raise self._protocol_error("missing_finish_reason")
        self._validate_calls(list(self.tool_fragments.values()))

    async def _buffered_tools(self):
        try:
            return await self._invoke()
        except DshUpstreamErrorError:
            if self.repair_tool_choice is None or self.protocol_failure not in {
                "invalid_tool_arguments",
                "unparsed_tool_call",
                "missing_tool_calls",
            }:
                raise
        # A completed but malformed generation has executed no tools. Ask the
        # model to correct its format once; never replay transport failures or
        # manufacture missing arguments. Preserve both invocations' usage.
        logger.warning("DSH correcting malformed tool generation once reason={}", self.protocol_failure)
        self.audit(
            "output",
            {
                "attempt": 1,
                "message": self.last_output,
                "finish_reason": self.finish_reason,
                "protocol_failure": self.protocol_failure,
                "released_to_client": False,
            },
        )
        first_usage = self.usage
        messages, llm = self.messages, self.llm
        self.messages = [
            *messages,
            HumanMessage(
                content=(
                    "Your previous response contained an incomplete or unparsed tool invocation. "
                    "Return a complete structured tool call using the provided tools. "
                    "Every parameter must have a complete JSON value. Omit unused optional parameters; "
                    "never emit an empty numeric or boolean value. Do not output tool XML as ordinary text."
                )
            ),
        ]
        self.llm = llm.bind(tool_choice=self.repair_tool_choice)
        self.audit(
            "output",
            {
                "protocol_repair": {
                    "attempt": 2,
                    "additional_input": self.messages[-1].model_dump(),
                    "tool_choice": self.repair_tool_choice,
                },
            },
        )
        self.usage = DshTokenUsage()
        self.finish_reason = None
        self.protocol_failure = None
        try:
            return await self._invoke()
        finally:
            second_usage = self.usage
            self.messages, self.llm = messages, llm
            if first_usage.total_tokens is None or second_usage.total_tokens is None:
                # An unknown invocation total cannot be silently counted as zero.
                self.usage = DshTokenUsage()
            else:
                self.usage = DshTokenUsage.model_validate(
                    {
                        name: (getattr(first_usage, name) + getattr(second_usage, name))
                        if getattr(first_usage, name) is not None and getattr(second_usage, name) is not None
                        else None
                        for name in DshTokenUsage.model_fields
                    }
                )


class DshChatAdapter:
    def prepare(
        self, request: DshChatRequest, llm, capabilities: ChatCapabilities, *, max_output_tokens: int | None = None
    ):
        if (request.stream and not capabilities.streaming) or (request.tools and not capabilities.tools):
            raise DshUnsupportedParameterError()
        # The enterprise Chat endpoint always produces Chat shapes, even for a
        # model that also enables native Responses. Copy only this call's SDK view.
        if hasattr(llm, "llm") and hasattr(llm.llm, "use_responses_api"):
            llm = llm.model_copy(update={"llm": llm.llm.model_copy(update={"use_responses_api": False})})
        if request.tools and not capabilities.tool_streaming:
            # Disable both wrapper and SDK streaming; ainvoke on a streaming
            # BishengLLM otherwise aggregates the same defective upstream SSE.
            updates = {"streaming": False}
            if hasattr(llm, "llm"):
                updates["llm"] = llm.llm.model_copy(update={"streaming": False})
            llm = llm.model_copy(update=updates)
        for field in ("max_completion_tokens", "stop", "temperature", "top_p"):
            if getattr(request, field) is not None and not getattr(capabilities, field):
                raise DshUnsupportedParameterError()
        output_limit = request.max_tokens or request.max_completion_tokens
        if max_output_tokens is not None and output_limit is not None and output_limit > max_output_tokens:
            raise DshInvalidRequestError()
        messages = []
        for item in request.messages:
            content = item.content
            if isinstance(content, list):
                if any(part.type == "image_url" for part in content) and not capabilities.vision:
                    raise DshUnsupportedParameterError()
                content = [part.model_dump() for part in content]
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
                message = message_type(content=content or "", additional_kwargs=extras)
            messages.append(message)
        parameters = {
            key: getattr(request, key)
            for key in ("max_tokens", "max_completion_tokens", "temperature", "top_p", "stop")
            if getattr(request, key) is not None
        }
        # MiniMax defaults to <think> text inside content. Request its native
        # separation so titles and normal answers never consume thinking text.
        # Keep reasoning_content intact for the next interleaved tool turn.
        if capabilities.reasoning_split:
            parameters["extra_body"] = {"reasoning_split": True}
        effort = request.reasoning_effort
        if effort is None and capabilities.reasoning is not None:
            effort = capabilities.reasoning.defaultEffort
        if effort is not None:
            if capabilities.reasoning is None or effort not in {item.id for item in capabilities.reasoning.efforts}:
                raise DshUnsupportedParameterError()
            parameters["reasoning_effort"] = effort
        if request.tools:
            choice = request.tool_choice or "auto"
            if isinstance(choice, SelectedTool):
                choice = choice.model_dump()
            llm = llm.bind_tools([tool.model_dump(exclude_none=True) for tool in request.tools], tool_choice=choice)
        elif request.tool_choice not in {None, "none"}:
            raise DshUnsupportedParameterError()
        execution = ChatExecution(llm, messages, parameters, capabilities)
        execution.allowed_tool_names = {tool.function.name for tool in request.tools or []}
        execution.repair_tool_choice = (
            None
            if request.tool_choice == "none"
            else request.tool_choice.model_dump()
            if isinstance(request.tool_choice, SelectedTool)
            else "required"
        )
        return execution
