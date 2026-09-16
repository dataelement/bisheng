"""F051 T014 (endpoint half): the call itself — pass-through, streaming, limits."""

import json
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage

from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.llm.domain.utils import LlmProviderDailyLimitExceededError
from test.open_api.model_gateway_fixtures import (
    FakeBishengLLM,
    build_model_face_app,
    capture_records,
    install_catalog,
    install_fake_llm,
    model_row,
    server_row,
    service_account_principal,
    text_chunk,
    tool_chunk,
    usage_chunk,
)

CHAT_PATH = "/api/v2/model/v1/chat/completions"
BODY = {"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]}


@pytest.fixture
def records(monkeypatch):
    monkeypatch.setattr(
        "bisheng.open_api.api.dependencies.validate_bearer",
        AsyncMock(return_value=service_account_principal()),
    )
    install_catalog(monkeypatch, [server_row(1, "azure-openai")], [model_row(10, 1, "gpt-4o")])
    return capture_records(monkeypatch)


async def _post(payload: dict):
    app = build_model_face_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post(CHAT_PATH, json=payload)


def _events(text: str) -> list:
    return [
        json.loads(line[len("data: ") :])
        for line in text.splitlines()
        if line.startswith("data: ") and line != "data: [DONE]"
    ]


async def test_a_non_streaming_call_returns_a_chat_completion(monkeypatch, records):
    install_fake_llm(
        monkeypatch,
        FakeBishengLLM(
            invoke_result=AIMessage(
                content="hello",
                usage_metadata={"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
            )
        ),
    )

    response = await _post(BODY)

    assert response.status_code == 200
    payload = response.json()
    assert payload["object"] == "chat.completion"
    assert payload["choices"][0]["message"]["content"] == "hello"
    assert payload["usage"]["total_tokens"] == 5
    assert records[0].result == "success"
    assert (records[0].prompt_tokens, records[0].total_tokens) == (3, 5)
    assert records[0].request_id == payload["id"]


async def test_the_model_is_built_for_this_face_and_charged_to_the_resource_owner(monkeypatch, records):
    fake = install_fake_llm(monkeypatch, FakeBishengLLM())

    await _post({**BODY, "temperature": 0.2})

    assert fake.init_kwargs["app_type"] is ApplicationTypeEnum.MODEL_GATEWAY
    assert fake.init_kwargs["user_id"] == 12
    assert fake.init_kwargs["streaming"] is False
    assert fake.init_kwargs["temperature"] == 0.2
    assert fake.init_kwargs["model_id"] == 10


async def test_sampling_parameters_and_tools_reach_the_model_untouched(monkeypatch, records):
    fake = install_fake_llm(monkeypatch, FakeBishengLLM())
    tools = [{"type": "function", "function": {"name": "read_file", "parameters": {}}}]

    await _post({**BODY, "top_p": 0.9, "stop": ["END"], "tools": tools, "tool_choice": "auto"})

    assert fake.bound == {"tools": tools, "tool_choice": "auto"}
    assert fake.seen_kwargs["top_p"] == 0.9
    assert fake.seen_kwargs["stop"] == ["END"]
    # Nothing was prepended: the caller's messages are the whole prompt.
    assert len(fake.seen_messages) == 1


async def test_streaming_carries_the_headers_that_stop_a_proxy_buffering_it(monkeypatch, records):
    install_fake_llm(monkeypatch, FakeBishengLLM(stream_script=[text_chunk("hi")]))

    app = build_model_face_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(CHAT_PATH, json={**BODY, "stream": True})

    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-accel-buffering"] == "no"
    assert response.headers["cache-control"] == "no-cache"
    assert response.text.endswith("data: [DONE]\n\n")


async def test_a_tool_calling_stream_round_trips_with_usage(monkeypatch, records):
    install_fake_llm(
        monkeypatch,
        FakeBishengLLM(
            stream_script=[
                tool_chunk(name="read_file", args='{"p"', call_id="call_1"),
                tool_chunk(name=None, args=':"a.py"}', call_id=None),
                usage_chunk(prompt=11, completion=4, finish_reason="tool_calls"),
            ]
        ),
    )

    app = build_model_face_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            CHAT_PATH, json={**BODY, "stream": True, "stream_options": {"include_usage": True}}
        )

    events = _events(response.text)
    finish = [item for item in events if item["choices"] and item["choices"][0].get("finish_reason")]
    usage = [item for item in events if item.get("usage")]
    tool_deltas = [
        call for item in events for choice in item["choices"] for call in choice["delta"].get("tool_calls", [])
    ]
    assert [call["index"] for call in tool_deltas] == [0, 0]
    assert finish[0]["choices"][0]["finish_reason"] == "tool_calls"
    assert usage[0]["usage"]["total_tokens"] == 15
    assert records[0].ttft_ms is not None
    assert records[0].total_tokens == 15


async def test_usage_is_recorded_even_when_the_caller_did_not_ask_for_it(monkeypatch, records):
    install_fake_llm(monkeypatch, FakeBishengLLM(stream_script=[text_chunk("hi"), usage_chunk(prompt=2, completion=1)]))

    app = build_model_face_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(CHAT_PATH, json={**BODY, "stream": True})

    assert not [item for item in _events(response.text) if item.get("usage")]
    assert records[0].total_tokens == 3


async def test_unknown_usage_is_recorded_as_null_not_zero(monkeypatch, records):
    install_fake_llm(monkeypatch, FakeBishengLLM(invoke_result=AIMessage(content="hi")))

    response = await _post(BODY)

    assert response.json()["usage"] is None
    assert records[0].prompt_tokens is None
    assert records[0].total_tokens is None


async def test_the_daily_provider_limit_is_a_real_429_not_half_a_stream(monkeypatch, records):
    install_fake_llm(
        monkeypatch,
        FakeBishengLLM(raise_on_first_chunk=LlmProviderDailyLimitExceededError("azure/gpt-4o Quota used up")),
    )

    response = await _post({**BODY, "stream": True})

    # The limit only fires on the first iteration; prefetching it is what keeps
    # this a status code rather than an error buried inside a 200 stream.
    assert response.status_code == 429
    body = response.json()["error"]
    assert body["bisheng_code"] == 26217
    assert body["type"] == "rate_limit_error"
    assert records[0].result == "limit_exceeded"


async def test_an_upstream_rejection_keeps_the_provider_status(monkeypatch, records):
    class Status(Exception):
        status_code = 413
        message = "context length exceeded"

    install_fake_llm(monkeypatch, FakeBishengLLM(raise_on_first_chunk=Status()))

    response = await _post({**BODY, "stream": True})

    assert response.status_code == 413
    assert response.json()["error"]["bisheng_code"] == 26232
    assert "context length exceeded" in response.json()["error"]["message"]


async def test_an_upstream_connection_failure_is_a_502(monkeypatch, records):
    install_fake_llm(monkeypatch, FakeBishengLLM(raise_on_invoke=ConnectionError("no route to host")))

    response = await _post(BODY)

    assert response.status_code == 502
    assert response.json()["error"]["bisheng_code"] == 26231
    assert records[0].result == "upstream_failed"
    assert records[0].total_tokens is None


async def test_a_mid_stream_failure_ends_the_stream_readably(monkeypatch, records):
    install_fake_llm(monkeypatch, FakeBishengLLM(stream_script=[text_chunk("par")], raise_after=1))

    app = build_model_face_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(CHAT_PATH, json={**BODY, "stream": True})

    # The 200 header is already out; the failure has to arrive as an event and
    # the connection must close rather than hang.
    assert response.status_code == 200
    errors = [item for item in _events(response.text) if "error" in item]
    assert errors[0]["error"]["bisheng_code"] == 26234
    assert response.text.endswith("data: [DONE]\n\n")
    assert records[0].result == "upstream_failed"


@pytest.mark.parametrize(
    ("platform_error", "expected_code", "expected_result"),
    [
        ("LlmModelConfigDeletedError", 26213, "model_unavailable"),
        ("LlmProviderDeletedError", 26213, "model_unavailable"),
        ("LlmModelOfflineError", 26212, "model_unavailable"),
        ("LlmModelTypeError", 26211, "model_unavailable"),
        ("InitLlmError", 26231, "upstream_failed"),
    ],
)
async def test_a_model_withdrawn_inside_the_cache_window_is_reported_as_such(
    monkeypatch, records, platform_error, expected_code, expected_result
):
    # The catalog caches for up to 60s, so a name can still resolve after an
    # administrator has deleted or taken down the model. Instantiation is where
    # that is discovered, and it is the only place 26212 / 26213 can come from:
    # deleting a provider deletes its model rows, leaving resolution nothing to
    # explain.
    import bisheng.common.errcode.server as server_errors
    from bisheng.llm.domain.services.llm import LLMService

    error_class = getattr(server_errors, platform_error)

    async def explode(**_kwargs):
        raise error_class()

    monkeypatch.setattr(LLMService, "get_bisheng_llm", staticmethod(explode))

    response = await _post(BODY)

    assert response.json()["error"]["bisheng_code"] == expected_code
    assert records[0].result == expected_result
    # The name the caller wrote is preserved even though the model is gone.
    assert records[0].requested_model == "gpt-4o"


async def test_a_client_that_walks_away_mid_stream_is_recorded_as_such(monkeypatch, records):
    install_fake_llm(
        monkeypatch,
        FakeBishengLLM(stream_script=[text_chunk("one"), text_chunk("two"), text_chunk("three")]),
    )
    calls = {"count": 0}

    async def disconnected_after_the_first_chunk(_self):
        calls["count"] += 1
        return calls["count"] > 1

    monkeypatch.setattr("starlette.requests.Request.is_disconnected", disconnected_after_the_first_chunk)

    app = build_model_face_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(CHAT_PATH, json={**BODY, "stream": True})

    # Not an upstream failure and not a success: nobody was listening, and the
    # ledger has to say so rather than book it as a completed call.
    assert response.status_code == 200
    assert records[0].result == "client_disconnected"


async def test_no_session_or_message_row_is_created(monkeypatch, records):
    from bisheng.database.models.session import MessageSessionDao

    install_fake_llm(monkeypatch, FakeBishengLLM(invoke_result=AIMessage(content="hi")))
    created: list = []
    for method in ("insert_one", "async_insert_one"):
        monkeypatch.setattr(
            MessageSessionDao,
            method,
            staticmethod(lambda *args, **kwargs: created.append(args)),
        )

    await _post(BODY)

    # This face is a different data plane from ``chat:invoke``: no session row,
    # nothing retrievable later, no message body anywhere.
    assert created == []
