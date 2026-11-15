"""Exercise provider validation through the real HTTP/SSE decoding stack."""

import json
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.messages import HumanMessage

from bisheng.common.services.failure_context import FailureContextAdapter
from bisheng.common.services.llm_error_classifier import Behavior, classify_behavior, label_error
from bisheng.core.ai import ChatOpenAICompatible
from bisheng.llm.domain.llm.llm import BishengLLM

METHODS = ["_stream", "_astream", "_generate", "_agenerate"]


def sse(*choices, usage=None):
    frames = [
        {"id": "mock", "object": "chat.completion.chunk", "model": "mock-model", "choices": [choice]}
        for choice in choices
    ]
    if usage:
        frames.append({"id": "mock", "model": "mock-model", "choices": [], "usage": usage})
    return "".join(f"data: {json.dumps(frame)}\n\n" for frame in frames).encode()


def choice(content="", finish_reason=None, **delta):
    return {"index": 0, "delta": {"content": content, **delta}, "finish_reason": finish_reason}


def model_for_body(body, *, streaming=True, requests=None, status=200):
    def respond(request):
        if requests is not None:
            requests.append(request)
        return httpx.Response(
            status,
            content=body,
            headers={"content-type": "text/event-stream" if streaming else "application/json"},
        )

    transport = httpx.MockTransport(respond)
    inner = ChatOpenAICompatible(
        model="mock-model",
        api_key="unused",
        base_url="https://model.invalid/v1",
        http_client=httpx.Client(transport=transport),
        http_async_client=httpx.AsyncClient(transport=transport),
        max_retries=0,
        streaming=streaming,
    )
    model = BishengLLM.model_construct(llm=inner)
    object.__setattr__(model, "model_info", SimpleNamespace(name="Mock model"))
    return model


async def invoke(model, method):
    # Skip quota/telemetry only; retain the model-service failure boundary.
    call = getattr(BishengLLM, method).__wrapped__
    messages = [HumanMessage(content="hi")]
    if method == "_stream":
        return list(call(model, messages))
    if method == "_astream":
        return [chunk async for chunk in call(model, messages)]
    if method == "_generate":
        return call(model, messages)
    return await call(model, messages)


@pytest.mark.parametrize("method", METHODS)
async def test_clean_eof_after_partial_text_fails_at_model_boundary(method):
    # No HTTP/socket exception occurs, yet the model never finished its response.
    model = model_for_body(sse(choice("Hello fr")))
    with pytest.raises(ConnectionError) as caught:
        await invoke(model, method)
    assert type(caught.value).__name__ == "IncompleteStreamError"
    info = FailureContextAdapter.from_error(caught.value)
    assert info["category"] == "model_service"
    assert info["service_name"] == "Mock model"
    assert classify_behavior(caught.value) is Behavior.RETRYABLE


@pytest.mark.parametrize("method", METHODS)
async def test_content_filter_finish_reason_is_classified_failure(method):
    model = model_for_body(sse(choice("partial"), choice(finish_reason="content_filter")))
    with pytest.raises(Exception) as caught:
        await invoke(model, method)
    assert getattr(caught.value, "code", None) == "content_filter"
    assert FailureContextAdapter.from_error(caught.value)["category"] == "model_service"
    assert classify_behavior(caught.value) is Behavior.DEGRADABLE
    assert label_error(caught.value).value == "content_filter"


@pytest.mark.parametrize("method", ["_generate", "_agenerate"])
async def test_non_streaming_content_filter_is_classified_failure(method):
    body = json.dumps(
        {
            "id": "mock",
            "object": "chat.completion",
            "model": "mock-model",
            "choices": [
                {"index": 0, "message": {"role": "assistant", "content": ""}, "finish_reason": "content_filter"}
            ],
        }
    ).encode()
    with pytest.raises(Exception) as caught:
        await invoke(model_for_body(body, streaming=False), method)
    assert getattr(caught.value, "code", None) == "content_filter"
    assert FailureContextAdapter.from_error(caught.value)["category"] == "model_service"


@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize("reason", ["stop", "length", "tool_calls", "function_call"])
async def test_valid_terminal_reason_accepts_empty_content(method, reason):
    await invoke(model_for_body(sse(choice(finish_reason=reason))), method)


@pytest.mark.parametrize("method", METHODS)
async def test_usage_only_completion_remains_compatible(method):
    # Some compatible providers omit finish_reason but send the terminal usage.
    await invoke(
        model_for_body(sse(choice("done"), usage={"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5})),
        method,
    )


@pytest.mark.parametrize("method", METHODS)
async def test_tool_call_without_finish_reason_keeps_existing_task_policy(method):
    await invoke(
        model_for_body(
            sse(
                choice(
                    tool_calls=[
                        {"index": 0, "id": "tool-1", "type": "function", "function": {"name": "f", "arguments": "{}"}}
                    ]
                )
            )
        ),
        method,
    )


@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize(
    "metadata,usage",
    [
        ({"stop_reason": "end_turn", "model_name": "claude"}, None),
        ({"model": "local", "done": True}, None),
        ({"model": "local", "done_reason": "stop"}, None),
        (
            {"model": "local", "done": True, "done_reason": "stop"},
            {"input_tokens": 4, "output_tokens": 1, "total_tokens": 5},
        ),
    ],
)
async def test_anthropic_and_ollama_completion_metadata_remains_compatible(method, metadata, usage):
    from langchain_core.messages import AIMessageChunk
    from langchain_core.outputs import ChatGenerationChunk

    chunk = ChatGenerationChunk(message=AIMessageChunk(content="", response_metadata=metadata, usage_metadata=usage))

    class Inner:
        streaming = True

        def _stream(self, *args, **kwargs):
            yield chunk

        async def _astream(self, *args, **kwargs):
            yield chunk

    model = BishengLLM.model_construct(llm=Inner())
    await invoke(model, method)


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_clean_eof_preserves_already_emitted_partial_text(asynchronous):
    model = model_for_body(sse(choice("Partial answer")))
    chunks = []
    with pytest.raises(ConnectionError):
        if asynchronous:
            async for chunk in BishengLLM._astream.__wrapped__(model, [HumanMessage(content="hi")]):
                chunks.append(chunk.message.content)
        else:
            for chunk in BishengLLM._stream.__wrapped__(model, [HumanMessage(content="hi")]):
                chunks.append(chunk.message.content)
    assert chunks == ["Partial answer"]


@pytest.mark.parametrize("method", ["_generate", "_agenerate"])
@pytest.mark.parametrize("body", [b'{"choices":', b"{}", b'{"choices": []}'])
async def test_malformed_non_streaming_response_keeps_safe_model_metadata(method, body):
    with pytest.raises(Exception) as caught:
        await invoke(model_for_body(body, streaming=False), method)
    info = FailureContextAdapter.from_error(caught.value)
    assert info["category"] == "model_service"
    assert info["service_name"] == "Mock model"
    public = FailureContextAdapter.public_payload({}, exc=caught.value)
    assert public["failure_info"] == info
    assert "model.invalid" not in json.dumps(public)


@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize("body", [b"", b"data: [DONE]\n\n", b'{"error":"not SSE"}'])
async def test_zero_decoded_chunks_fail_inside_model_boundary(method, body):
    with pytest.raises(ValueError) as caught:
        await invoke(model_for_body(body), method)
    assert FailureContextAdapter.from_error(caught.value)["category"] == "model_service"


@pytest.mark.parametrize("method", METHODS)
async def test_native_ollama_done_without_token_usage_through_real_sdk(method):
    from langchain_ollama import ChatOllama

    frames = [
        {"model": "local", "message": {"role": "assistant", "content": "done"}, "done": False},
        {"model": "local", "message": {"role": "assistant", "content": ""}, "done": True, "done_reason": "stop"},
    ]
    body = "\n".join(json.dumps(frame) for frame in frames).encode()
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=body))
    inner = ChatOllama(model="local", base_url="https://ollama.invalid", client_kwargs={"transport": transport})
    result = await invoke(BishengLLM.model_construct(llm=inner), method)
    if isinstance(result, list):
        assert "".join(chunk.message.content for chunk in result) == "done"
    else:
        assert result.generations[0].message.content == "done"
