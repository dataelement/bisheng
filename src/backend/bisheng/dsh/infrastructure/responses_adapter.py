"""Native Responses execution, using the configured SDK client without Chat conversion."""

import json

import httpx
from pydantic import TypeAdapter, ValidationError

from bisheng.common.errcode.dsh import DshInvalidRequestError, DshUnsupportedParameterError, DshUpstreamErrorError
from bisheng.dsh.domain.schemas.contracts import DshTokenUsage
from bisheng.dsh.domain.schemas.responses import (
    MAX_EVENT_BYTES,
    MAX_RESPONSE_BYTES,
    FunctionCall,
    InputImage,
    InputItem,
    Message,
)

OUTPUT_ITEM = TypeAdapter(InputItem)
TERMINAL = {"response.completed", "response.failed", "response.incomplete"}
EVENTS = TERMINAL | {
    "response.created",
    "response.in_progress",
    "response.output_item.added",
    "response.output_item.done",
    "response.content_part.added",
    "response.content_part.done",
    "response.output_text.delta",
    "response.output_text.done",
    "response.output_text.annotation.added",
    "response.refusal.delta",
    "response.refusal.done",
    "response.reasoning_summary_part.added",
    "response.reasoning_summary_part.done",
    "response.reasoning_summary_text.delta",
    "response.reasoning_summary_text.done",
    "response.reasoning_text.delta",
    "response.reasoning_text.done",
    "response.function_call_arguments.delta",
    "response.function_call_arguments.done",
}


class BoundedSupplierStream(httpx.AsyncByteStream):
    """Bound raw bytes before the SDK's JSON/SSE decoder buffers them."""

    def __init__(self, source):
        self.source = source

    async def __aiter__(self):
        size = 0
        async for chunk in self.source:
            size += len(chunk)
            if size > MAX_RESPONSE_BYTES:
                raise DshUpstreamErrorError()
            yield chunk

    async def aclose(self):
        await self.source.aclose()


def normalize_responses_usage(raw) -> DshTokenUsage:
    if not isinstance(raw, dict):
        return DshTokenUsage()
    try:
        usage = DshTokenUsage.model_validate(
            {key: raw.get(key) for key in ("input_tokens", "output_tokens", "total_tokens")}
        )
    except ValidationError:
        return DshTokenUsage()
    details = raw.get("input_tokens_details") or {}
    for source, target in (("cached_tokens", "cache_read_tokens"), ("cache_creation_tokens", "cache_creation_tokens")):
        value = details.get(source) if isinstance(details, dict) else None
        if type(value) is int and 0 <= value <= 9223372036854775807:
            setattr(usage, target, value)
    return usage


class ResponsesExecution:
    def __init__(self, client, request, parameters):
        self.client, self.request, self.parameters = client, request, parameters
        self.usage = DshTokenUsage()
        self.provider_request_id = None
        self.status = "SUCCEEDED"
        self.source = None
        self.bytes = 0
        self.terminal = False
        self.sequence = -1

    def _bounded(self, value):
        size = len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())
        self.bytes += size
        if size > MAX_EVENT_BYTES or self.bytes > MAX_RESPONSE_BYTES:
            raise DshUpstreamErrorError()

    def _response(self, raw):
        self.provider_request_id = raw.get("id")
        self.usage = normalize_responses_usage(raw.get("usage"))
        if raw.get("status") not in {"completed", "failed", "incomplete"}:
            raise DshUpstreamErrorError()
        output = raw.get("output")
        if not isinstance(output, list) or len(output) > 4096:
            raise DshUpstreamErrorError()
        names = {tool.name for tool in self.request.tools or []}
        seen = set()
        for item in output:
            try:
                parsed = OUTPUT_ITEM.validate_python(item)
            except ValidationError as exc:
                raise DshUpstreamErrorError() from exc
            if parsed.type not in {"message", "reasoning", "function_call"}:
                raise DshUpstreamErrorError()
            if isinstance(parsed, Message) and parsed.role != "assistant":
                raise DshUpstreamErrorError()
            if isinstance(parsed, FunctionCall):
                if parsed.name not in names or parsed.call_id in seen:
                    raise DshUpstreamErrorError()
                seen.add(parsed.call_id)
        result = {**raw, "model": self.request.model}
        if raw.get("error") is not None:
            result["error"] = {"code": "upstream_error", "message": "The model request failed."}
        if raw["status"] == "failed":
            self.status = "FAILED"
        return result

    async def invoke(self):
        async with self.client.responses.with_streaming_response.create(**self.parameters) as response:
            response.http_response.stream = BoundedSupplierStream(response.http_response.stream)
            parsed = await response.parse()
            raw = parsed.model_dump(mode="json", exclude_unset=True)
            self.usage = normalize_responses_usage(raw.get("usage"))
            self._bounded(raw)
            return self._response(raw)

    async def stream(self):
        async with self.client.responses.with_streaming_response.create(**self.parameters) as response:
            response.http_response.stream = BoundedSupplierStream(response.http_response.stream)
            self.source = await response.parse()
            events = self._events()
            try:
                async for event in events:
                    yield event
            finally:
                await events.aclose()

    async def _events(self):
        try:
            async for event in self.source:
                raw = event.model_dump(mode="json", exclude_unset=True)
                kind = raw.get("type", "")
                if kind in TERMINAL and isinstance(raw.get("response"), dict):
                    self.usage = normalize_responses_usage(raw["response"].get("usage"))
                self._bounded(raw)
                sequence = raw.get("sequence_number")
                if self.terminal or type(sequence) is not int or sequence <= self.sequence:
                    raise DshUpstreamErrorError()
                self.sequence = sequence
                # Reject unnegotiated output families before forwarding their deltas.
                if kind not in EVENTS:
                    raise DshUpstreamErrorError()
                if kind in {"response.output_item.added", "response.output_item.done"}:
                    if (raw.get("item") or {}).get("type") not in {"message", "reasoning", "function_call"}:
                        raise DshUpstreamErrorError()
                if kind in TERMINAL:
                    if raw["response"].get("status") != kind.removeprefix("response."):
                        raise DshUpstreamErrorError()
                    raw["response"] = self._response(raw["response"])
                    self.terminal = True
                elif "response" in raw:
                    raw["response"]["model"] = self.request.model
                    if raw["response"].get("error"):
                        raise DshUpstreamErrorError()
                yield raw
            if not self.terminal:
                raise DshUpstreamErrorError()
        finally:
            await self.source.close()


class DshResponsesAdapter:
    def prepare(self, request, llm, capabilities, *, max_output_tokens=None):
        if (
            not capabilities.responses
            or (request.stream and not capabilities.streaming)
            or (request.tools and not capabilities.tools)
        ):
            raise DshUnsupportedParameterError()
        if (
            max_output_tokens is not None
            and request.max_output_tokens is not None
            and request.max_output_tokens > max_output_tokens
        ):
            raise DshInvalidRequestError()
        if not capabilities.vision:
            for item in request.input:
                blocks = getattr(item, "content", getattr(item, "output", []))
                if isinstance(blocks, list) and any(isinstance(part, InputImage) for part in blocks):
                    raise DshUnsupportedParameterError()
        parameters = request.model_dump(exclude_none=True, exclude={"model"})
        parameters.update(model=llm.model_name, store=False, include=["reasoning.encrypted_content"])
        if max_output_tokens is not None and request.max_output_tokens is None:
            parameters["max_output_tokens"] = max_output_tokens
        effort = request.reasoning.effort if request.reasoning else None
        if request.reasoning is not None and capabilities.reasoning is None:
            raise DshUnsupportedParameterError()
        if effort is None and capabilities.reasoning:
            effort = capabilities.reasoning.defaultEffort
        if effort is not None:
            if capabilities.reasoning is None or effort not in {item.id for item in capabilities.reasoning.efforts}:
                raise DshUnsupportedParameterError()
            parameters["reasoning"] = {**parameters.get("reasoning", {}), "effort": effort}
        client = llm.llm.root_async_client
        return ResponsesExecution(client, request, parameters)
