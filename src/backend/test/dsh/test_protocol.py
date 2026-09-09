"""覆盖 AC: AC-18, AC-19, AC-20, AC-21, AC-23, AC-24."""

from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk
from pydantic import ValidationError

from bisheng.common.errcode.dsh import DshUnsupportedParameterError
from bisheng.dsh.domain.schemas.chat import ChatCapabilities, DshChatRequest
from bisheng.dsh.infrastructure.chat_adapter import DshChatAdapter


def request(**kwargs):
    return DshChatRequest(model="bisheng:42", messages=[{"role": "user", "content": "hello"}], **kwargs)


@pytest.mark.parametrize(
    "extra",
    [
        {"temperature": True},
        {"unknown": 1},
        {"n": 2},
        {"max_tokens": 1, "max_completion_tokens": 1},
        {"stream_options": {"include_usage": True}},
        {"stream": True, "stream_options": {"include_usage": 1}},
        {"tool_choice": "required"},
        {"stop": []},
    ],
)
def test_strict_request_rejects_unsupported_shapes(extra):
    with pytest.raises(ValidationError):
        request(**extra)


def test_tool_multiturn_ids_and_string_arguments():
    messages = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "f", "arguments": '{"x":1}'}}],
        },
        {"role": "tool", "tool_call_id": "c1", "content": "ok"},
        {"role": "user", "content": "continue"},
    ]
    assert DshChatRequest(model="bisheng:42", messages=messages).model_id == 42
    messages[1]["tool_call_id"] = "another"
    with pytest.raises(ValidationError):
        DshChatRequest(model="bisheng:42", messages=messages)


class FakeLLM:
    def __init__(self):
        self.calls = []

    def bind_tools(self, tools, **kwargs):
        self.calls.append(("bind_tools", tools, kwargs))
        return self

    async def ainvoke(self, messages, **kwargs):
        self.calls.append(("ainvoke", messages, kwargs))
        return AIMessage(
            content="answer",
            usage_metadata={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
            response_metadata={"finish_reason": "stop"},
        )

    async def astream(self, messages, **kwargs):
        self.calls.append(("astream", messages, kwargs))
        yield AIMessageChunk(content="", tool_call_chunks=[{"index": 0, "id": "call-1", "name": "f", "args": '{"x":'}])
        yield AIMessageChunk(content="", tool_call_chunks=[{"index": 0, "id": None, "name": None, "args": "1}"}])
        yield AIMessageChunk(content="", response_metadata={"finish_reason": "tool_calls"})
        yield AIMessageChunk(content="", usage_metadata={"input_tokens": 10, "output_tokens": 3, "total_tokens": 13})


async def test_nonstream_stays_on_governed_wrapper_and_preserves_usage():
    llm = FakeLLM()
    call = DshChatAdapter().prepare(request(max_tokens=5), llm, ChatCapabilities())
    result = await call.invoke()
    assert result["message"]["content"] == "answer"
    assert call.usage.total_tokens == 12
    assert llm.calls[0][0] == "ainvoke"
    assert llm.calls[0][2]["max_tokens"] == 5


async def test_tool_chunks_preserve_argument_fragments_and_finish_reason():
    llm = FakeLLM()
    body = request(
        stream=True, tools=[{"type": "function", "function": {"name": "f", "parameters": {"type": "object"}}}]
    )
    call = DshChatAdapter().prepare(body, llm, ChatCapabilities())
    chunks = [chunk async for chunk in call.stream()]
    assert chunks[0]["tool_calls"][0]["function"]["arguments"] == '{"x":'
    assert chunks[1]["tool_calls"][0]["function"]["arguments"] == "1}"
    assert call.finish_reason == "tool_calls"
    assert call.usage.total_tokens == 13
    assert llm.calls[0][0] == "bind_tools"
    assert llm.calls[1][0] == "astream"


def test_capabilities_refuse_unverified_extensions():
    with pytest.raises(DshUnsupportedParameterError):
        DshChatAdapter().prepare(request(max_completion_tokens=5), FakeLLM(), ChatCapabilities())
    body = DshChatRequest(
        model="bisheng:42", messages=[{"role": "assistant", "content": "x", "reasoning_content": "r"}]
    )
    with pytest.raises(DshUnsupportedParameterError):
        DshChatAdapter().prepare(body, FakeLLM(), ChatCapabilities())


async def test_missing_usage_is_unknown_not_zero():
    async def invoke(*args, **kwargs):
        return AIMessage(content="answer", response_metadata={"finish_reason": "stop"})

    call = DshChatAdapter().prepare(request(), SimpleNamespace(ainvoke=invoke), ChatCapabilities())
    await call.invoke()
    assert call.usage.total_tokens is None


async def test_incomplete_tool_arguments_never_become_success():
    from bisheng.common.errcode.dsh import DshUpstreamErrorError

    class Incomplete(FakeLLM):
        async def astream(self, messages, **kwargs):
            yield AIMessageChunk(content="", tool_call_chunks=[{"index": 0, "id": "c", "name": "f", "args": '{"x":'}])
            yield AIMessageChunk(content="", response_metadata={"finish_reason": "tool_calls"})

    body = request(stream=True, tools=[{"type": "function", "function": {"name": "f", "parameters": {}}}])
    call = DshChatAdapter().prepare(body, Incomplete(), ChatCapabilities())
    with pytest.raises(DshUpstreamErrorError):
        _chunks = [chunk async for chunk in call.stream()]
