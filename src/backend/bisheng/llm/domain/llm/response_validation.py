"""Validate provider outcomes that SDKs can return without raising an error."""

from collections.abc import AsyncIterator, Iterator

from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult


class IncompleteStreamError(ConnectionError):
    """A provider stream ended without completion, usage, or a tool call.

    Keep this a ConnectionError for the existing transient-error label. Task
    resilience gives it a separate, bounded retry budget from transport errors.
    """


class ModelContentFilterError(RuntimeError):
    """The provider explicitly rejected the response under its content policy."""

    code = "content_filter"


def has_completion_marker(metadata: dict) -> bool:
    """Recognize OpenAI/Anthropic reasons and native Ollama completion signals."""
    return bool(
        metadata.get("finish_reason")
        or metadata.get("stop_reason")
        or metadata.get("done_reason")
        or metadata.get("done") is True
    )


class _StreamValidation:
    def __init__(self):
        self.received_chunk = False
        self.has_metadata = False
        self.finished = False
        self.has_input_usage = False
        self.has_tool_call = False

    def observe(self, generation: ChatGeneration) -> None:
        self.received_chunk = True
        message = generation.message
        metadata = {**message.response_metadata, **(generation.generation_info or {})}
        self.has_metadata |= bool(metadata)
        reason = metadata.get("finish_reason") or metadata.get("stop_reason")
        if reason == "content_filter":
            raise ModelContentFilterError("Model response was rejected by the provider content filter")
        self.finished |= has_completion_marker(metadata)
        self.has_input_usage |= bool((getattr(message, "usage_metadata", None) or {}).get("input_tokens"))
        self.has_tool_call |= bool(
            getattr(message, "tool_calls", None)
            or getattr(message, "invalid_tool_calls", None)
            or getattr(message, "tool_call_chunks", None)
            or message.additional_kwargs.get("tool_calls")
            or message.additional_kwargs.get("function_call")
        )

    def finish(self) -> None:
        if not self.received_chunk:
            # SDKs may silently consume a non-SSE HTTP 200 response.
            raise ValueError("Model returned no stream chunks")
        # Preserve the task guard's conservative fingerprint: synthetic messages,
        # usage-only completions and unfinished tool calls remain out of scope.
        if self.has_metadata and not (self.finished or self.has_input_usage or self.has_tool_call):
            raise IncompleteStreamError("Provider closed the response stream before the turn finished")


def validate_stream(stream: Iterator[ChatGenerationChunk]) -> Iterator[ChatGenerationChunk]:
    validation = _StreamValidation()
    for chunk in stream:
        validation.observe(chunk)
        yield chunk
    validation.finish()


async def validate_astream(stream: AsyncIterator[ChatGenerationChunk]) -> AsyncIterator[ChatGenerationChunk]:
    validation = _StreamValidation()
    async for chunk in stream:
        validation.observe(chunk)
        yield chunk
    validation.finish()


def validate_result(result: ChatResult) -> None:
    # Non-streaming calls have no EOF fingerprint, but can still be rejected with
    # HTTP 200 and finish_reason=content_filter instead of a provider exception.
    if not result.generations:
        raise ValueError("Model returned no generations")
    for generation in result.generations:
        _StreamValidation().observe(generation)
