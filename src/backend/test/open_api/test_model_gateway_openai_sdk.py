"""F051 T019: the promise is "the official client just works".

Everything else in this feature asserts our own view of the wire. This file
asserts the client's: if ``openai.AsyncOpenAI`` cannot parse a response or
raises the wrong exception class, the face has failed its headline claim, even
when every field looks right to us.
"""

from unittest.mock import AsyncMock

import httpx
import openai
import pytest
from langchain_core.messages import AIMessage

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

MESSAGES = [{"role": "user", "content": "hi"}]


@pytest.fixture
def face(monkeypatch):
    monkeypatch.setattr(
        "bisheng.open_api.api.dependencies.validate_bearer",
        AsyncMock(return_value=service_account_principal()),
    )
    install_catalog(
        monkeypatch,
        [server_row(1, "azure-openai"), server_row(2, "qwen-cloud")],
        [model_row(10, 1, "gpt-4o"), model_row(11, 1, "shared"), model_row(12, 2, "shared")],
    )
    capture_records(monkeypatch)
    return build_model_face_app()


def client_for(app) -> openai.AsyncOpenAI:
    return openai.AsyncOpenAI(
        base_url="http://test/api/v2/model/v1",
        # Never validated here — validate_bearer is stubbed — but the client
        # refuses to construct without one.
        api_key="unit-test-placeholder",
        http_client=httpx.AsyncClient(transport=httpx.ASGITransport(app=app)),
        max_retries=0,
    )


async def test_the_client_lists_models_and_every_id_is_callable(monkeypatch, face):
    install_fake_llm(monkeypatch, FakeBishengLLM(invoke_result=AIMessage(content="ok")))
    client = client_for(face)

    listing = await client.models.list()

    ids = {model.id for model in listing.data}
    assert ids == {"gpt-4o", "azure-openai/shared", "qwen-cloud/shared"}
    for model_id in ids:
        completion = await client.chat.completions.create(model=model_id, messages=MESSAGES)
        assert completion.choices[0].message.content == "ok"


async def test_the_client_parses_a_non_streaming_completion_with_usage(monkeypatch, face):
    install_fake_llm(
        monkeypatch,
        FakeBishengLLM(
            invoke_result=AIMessage(
                content="hello",
                usage_metadata={"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
            )
        ),
    )

    completion = await client_for(face).chat.completions.create(model="gpt-4o", messages=MESSAGES)

    assert completion.object == "chat.completion"
    assert completion.usage.total_tokens == 5
    assert completion.choices[0].finish_reason == "stop"


async def test_the_client_accumulates_a_tool_calling_stream(monkeypatch, face):
    install_fake_llm(
        monkeypatch,
        FakeBishengLLM(
            stream_script=[
                text_chunk("thinking"),
                tool_chunk(name="read_file", args='{"p"', call_id="call_1"),
                tool_chunk(name=None, args=':"a.py"}', call_id=None),
                usage_chunk(prompt=11, completion=4, finish_reason="tool_calls"),
            ]
        ),
    )

    stream = await client_for(face).chat.completions.create(
        model="gpt-4o",
        messages=MESSAGES,
        stream=True,
        stream_options={"include_usage": True},
    )

    text = ""
    arguments = ""
    usage = None
    finish_reason = None
    async for chunk in stream:
        if chunk.usage is not None:
            usage = chunk.usage
        for choice in chunk.choices:
            text += choice.delta.content or ""
            for call in choice.delta.tool_calls or []:
                arguments += call.function.arguments or ""
            finish_reason = choice.finish_reason or finish_reason

    assert text == "thinking"
    # The SDK concatenates by index — the whole point of assigning one.
    assert arguments == '{"p":"a.py"}'
    assert finish_reason == "tool_calls"
    assert usage.total_tokens == 15


@pytest.mark.parametrize(
    ("side_effect", "expected"),
    [
        ("missing_credential", openai.AuthenticationError),
        ("missing_scope", openai.PermissionDeniedError),
    ],
)
async def test_admission_failures_raise_the_clients_own_exception_classes(monkeypatch, side_effect, expected):
    from bisheng.common.errcode.open_api import OpenApiCredentialMissingError, OpenApiScopeMissingError

    error = (
        OpenApiCredentialMissingError()
        if side_effect == "missing_credential"
        else OpenApiScopeMissingError(required="model:invoke")
    )
    monkeypatch.setattr(
        "bisheng.open_api.api.dependencies.validate_bearer",
        AsyncMock(side_effect=error),
    )

    with pytest.raises(expected) as excinfo:
        await client_for(build_model_face_app()).models.list()

    assert excinfo.value.body["bisheng_code"] == error.code


async def test_an_unknown_model_raises_not_found(monkeypatch, face):
    install_fake_llm(monkeypatch, FakeBishengLLM())

    with pytest.raises(openai.NotFoundError) as excinfo:
        await client_for(face).chat.completions.create(model="never-configured", messages=MESSAGES)

    assert excinfo.value.body["code"] == "model_not_found"


async def test_an_ambiguous_name_raises_bad_request_and_names_the_alternatives(monkeypatch, face):
    install_fake_llm(monkeypatch, FakeBishengLLM())

    with pytest.raises(openai.BadRequestError) as excinfo:
        await client_for(face).chat.completions.create(model="shared", messages=MESSAGES)

    assert excinfo.value.body["candidates"] == ["azure-openai/shared", "qwen-cloud/shared"]


async def test_the_provider_daily_limit_raises_rate_limit_error(monkeypatch, face):
    from bisheng.llm.domain.utils import LlmProviderDailyLimitExceededError

    install_fake_llm(
        monkeypatch,
        FakeBishengLLM(raise_on_invoke=LlmProviderDailyLimitExceededError("azure/gpt-4o Quota used up")),
    )

    with pytest.raises(openai.RateLimitError) as excinfo:
        await client_for(face).chat.completions.create(model="gpt-4o", messages=MESSAGES)

    assert excinfo.value.body["bisheng_code"] == 26217


async def test_an_endpoint_outside_the_promise_raises_not_found(monkeypatch, face):
    install_fake_llm(monkeypatch, FakeBishengLLM())

    with pytest.raises(openai.NotFoundError) as excinfo:
        await client_for(face).embeddings.create(model="gpt-4o", input="hi")

    assert excinfo.value.body["bisheng_code"] == 26201
