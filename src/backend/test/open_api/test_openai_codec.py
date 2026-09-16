"""F051 T014 (codec half): translation between OpenAI shapes and langchain."""

import json

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage, ToolMessage

from bisheng.common.errcode.model_face import (
    ModelFaceStreamInterruptedError,
    ModelFaceUpstreamError,
    ModelFaceUpstreamRateLimitedError,
    ModelFaceUpstreamRejectedError,
)
from bisheng.open_api.domain.schemas.model_gateway import ChatCompletionRequest
from bisheng.open_api.domain.services.openai_codec import (
    ChunkAssembler,
    build_completion,
    classify_stream_error,
    classify_upstream_error,
    redact_secrets,
    to_langchain_messages,
    usage_from,
)
from test.open_api.model_gateway_fixtures import text_chunk, tool_chunk, usage_chunk


def _payload(line: str) -> dict:
    assert line.startswith("data: ")
    return json.loads(line[len("data: ") :])


def test_every_conversation_role_survives_the_conversion():
    messages = to_langchain_messages(
        [
            {"role": "system", "content": "be terse"},
            {"role": "user", "content": "read config.py"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_1", "type": "function", "function": {"name": "read_file", "arguments": '{"p":"a"}'}}
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "file body"},
        ]
    )

    assert [type(message) for message in messages] == [SystemMessage, HumanMessage, AIMessage, ToolMessage]
    assert messages[2].tool_calls[0]["name"] == "read_file"
    assert messages[3].tool_call_id == "call_1"


def test_multimodal_content_arrays_are_passed_through_unchanged():
    content = [{"type": "text", "text": "what is this"}, {"type": "image_url", "image_url": {"url": "data:..."}}]

    messages = to_langchain_messages([{"role": "user", "content": content}])

    assert messages[0].content == content


def test_enumerated_and_unknown_request_fields_are_both_forwarded():
    request = ChatCompletionRequest(
        model="gpt-4o",
        messages=[{"role": "user", "content": "hi"}],
        top_p=0.3,
        max_tokens=64,
        stop=["END"],
        # Not in the promised enumeration: forwarded, not guaranteed.
        logit_bias={"1": 2},
    )

    kwargs = request.forwarded_kwargs()

    assert kwargs["top_p"] == 0.3
    assert kwargs["max_tokens"] == 64
    assert kwargs["stop"] == ["END"]
    assert kwargs["logit_bias"] == {"1": 2}
    # Temperature is handed to the model at construction, not as a call kwarg.
    assert "temperature" not in kwargs


def test_completion_renders_tool_call_arguments_as_a_json_string():
    message = AIMessage(
        content="",
        tool_calls=[{"name": "read_file", "args": {"path": "a.py"}, "id": "call_1", "type": "tool_call"}],
        usage_metadata={"input_tokens": 4, "output_tokens": 7, "total_tokens": 11},
    )

    completion = build_completion(message, model="gpt-4o", request_id="chatcmpl-x")

    choice = completion.choices[0]
    assert choice.finish_reason == "tool_calls"
    assert choice.message.tool_calls[0].function.arguments == '{"path": "a.py"}'
    assert (completion.usage.prompt_tokens, completion.usage.total_tokens) == (4, 11)


def test_unknown_usage_is_none_rather_than_zero():
    assert usage_from(AIMessage(content="hi")) is None
    assert usage_from(usage_chunk(prompt=2, completion=3)).total_tokens == 5


def test_reasoning_content_is_omitted_when_absent():
    completion = build_completion(AIMessage(content="hi"), model="m", request_id="chatcmpl-x")

    assert completion.choices[0].message.reasoning_content is None
    assert "reasoning_content" not in completion.model_dump(exclude_none=True)["choices"][0]["message"]


def test_stream_assembles_role_text_finish_and_usage():
    assembler = ChunkAssembler(model="gpt-4o", request_id="chatcmpl-x")

    prelude = _payload(assembler.role_prelude())
    first = _payload(assembler.next(text_chunk("Hel")))
    second = _payload(assembler.next(text_chunk("lo")))
    assembler.next(usage_chunk(prompt=2, completion=3))
    finish = _payload(assembler.finish())
    usage = _payload(assembler.usage(include_usage=True))

    assert prelude["choices"][0]["delta"]["role"] == "assistant"
    assert first["choices"][0]["delta"]["content"] == "Hel"
    assert second["object"] == "chat.completion.chunk"
    assert finish["choices"][0]["finish_reason"] == "stop"
    assert usage["choices"] == []
    assert usage["usage"]["total_tokens"] == 5


def test_no_usage_chunk_when_the_caller_did_not_ask_for_one():
    assembler = ChunkAssembler(model="gpt-4o", request_id="chatcmpl-x")
    assembler.next(usage_chunk(prompt=2, completion=3))

    assert assembler.usage(include_usage=False) is None


def test_parallel_tool_calls_keep_distinct_indices_when_upstream_sends_none():
    # qwen / zhipu deliver index=None and put the id only on the first fragment.
    # Forwarding that verbatim concatenates two calls' arguments into one.
    assembler = ChunkAssembler(model="gpt-4o", request_id="chatcmpl-x")
    assembler.role_prelude()

    first = _payload(assembler.next(tool_chunk(name="read_file", args='{"p"', call_id="call_1")))
    first_more = _payload(assembler.next(tool_chunk(name=None, args=':"a.py"}', call_id=None)))
    second = _payload(assembler.next(tool_chunk(name="list_dir", args="{}", call_id="call_2")))

    assert first["choices"][0]["delta"]["tool_calls"][0]["index"] == 0
    assert first_more["choices"][0]["delta"]["tool_calls"][0]["index"] == 0
    assert second["choices"][0]["delta"]["tool_calls"][0]["index"] == 1
    assert _payload(assembler.finish())["choices"][0]["finish_reason"] == "tool_calls"


def test_reasoning_only_chunks_are_emitted_and_empty_chunks_are_not():
    assembler = ChunkAssembler(model="gpt-4o", request_id="chatcmpl-x")

    thinking = assembler.next(AIMessageChunk(content="", additional_kwargs={"reasoning_content": "hmm"}))
    empty = assembler.next(AIMessageChunk(content=""))

    assert _payload(thinking)["choices"][0]["delta"]["reasoning_content"] == "hmm"
    assert empty is None


def test_upstream_status_decides_the_band():
    class Status(Exception):
        def __init__(self, status_code, message):
            super().__init__(message)
            self.status_code = status_code
            self.message = message

    rejected = classify_upstream_error(Status(413, "context too long"))
    limited = classify_upstream_error(Status(429, "slow down"))
    failed = classify_upstream_error(ConnectionError("no route to host"))

    assert isinstance(rejected, ModelFaceUpstreamRejectedError)
    assert rejected.http_status == 413
    assert "context too long" in rejected.message
    assert isinstance(limited, ModelFaceUpstreamRateLimitedError)
    assert isinstance(failed, ModelFaceUpstreamError)


def test_unrecognised_upstream_text_is_truncated():
    error = classify_upstream_error(RuntimeError("x" * 900))

    assert len(error.message) == 500


def test_mid_stream_failure_without_a_status_is_stream_interrupted():
    assert isinstance(classify_stream_error(RuntimeError("socket closed")), ModelFaceStreamInterruptedError)


@pytest.mark.parametrize(
    "text",
    [
        "auth failed for bs-sak-abcdefghijklmnop",
        "Incorrect API key provided: sk-proj-abcdefghijklmnop",
        "header was Bearer eyJhbGciOi.payload.sig",
    ],
)
def test_key_shaped_text_never_survives_into_a_message(text):
    redacted = redact_secrets(text)

    assert "[redacted]" in redacted
    assert "bs-sak-abcdefghijklmnop" not in redacted
    assert "sk-proj-abcdefghijklmnop" not in redacted
    assert "eyJhbGciOi.payload.sig" not in redacted


def test_stream_error_event_carries_the_openai_shape():
    payload = _payload(ChunkAssembler.error(ModelFaceStreamInterruptedError()))["error"]

    assert payload["bisheng_code"] == 26234
    assert payload["type"] == "server_error"
    assert payload["code"] == "stream_interrupted"
