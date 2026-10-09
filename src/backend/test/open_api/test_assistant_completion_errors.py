"""Error contract of POST /api/v2/assistant/chat/completions."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessageChunk

from bisheng.assistant.domain.services.published_assistant_service import (
    AssistantCompletion,
    PublishedAssistantService,
)
from bisheng.common.errcode.assistant import AssistantModelNotConfigError
from bisheng.common.errcode.http_error import NotFoundError
from bisheng.main import app
from test.open_api.test_dependencies import service_account_principal

ENDPOINT = "/api/v2/assistant/chat/completions"
ASSISTANT_ID = "00000000-0000-0000-0000-000000000001"


@pytest.fixture
def authorized(monkeypatch):
    monkeypatch.setattr(
        "bisheng.open_api.api.dependencies.validate_bearer",
        AsyncMock(return_value=service_account_principal(scopes=frozenset({"assistant:invoke"}))),
    )
    monkeypatch.setattr(
        "bisheng.open_endpoints.api.endpoints.assistant.get_open_api_operator", lambda: SimpleNamespace(user_id=12)
    )
    monkeypatch.setattr("bisheng.open_endpoints.api.endpoints.assistant.telemetry_service.log_event", AsyncMock())


async def _post(body: dict):
    # Unhandled errors are re-raised by Starlette after the 500 response is sent.
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(ENDPOINT, json=body, headers={"Authorization": "Bearer bs-sak-test"})


def _sse_payloads(text: str) -> list[str]:
    return [line.removeprefix("data: ") for line in text.split("\n\n") if line.startswith("data: ")]


def _failing_stream(error: Exception):
    async def stream():
        chunk = {"object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {"content": "par"}}]}
        yield f"data: {json.dumps(chunk)}\n\n"
        raise error

    return stream()


@pytest.mark.parametrize(
    "error,expected",
    [
        (
            AssistantModelNotConfigError(),
            {"message": AssistantModelNotConfigError.Msg, "type": "invalid_request_error", "code": 10423},
        ),
        (NotFoundError(), {"message": NotFoundError.Msg, "type": "not_found_error", "code": 404}),
        (
            RuntimeError("model gateway timed out"),
            {"message": "model gateway timed out", "type": "server_error", "code": None},
        ),
    ],
)
async def test_stream_error_is_an_openai_error_event_followed_by_done(authorized, monkeypatch, error, expected):
    complete = AsyncMock(
        return_value=(AssistantCompletion(payload=None, stream=_failing_stream(error)), SimpleNamespace(name="a"))
    )
    monkeypatch.setattr("bisheng.open_endpoints.api.endpoints.assistant.PublishedAssistantService.complete", complete)

    response = await _post({"model": ASSISTANT_ID, "messages": [{"role": "user", "content": "hi"}], "stream": True})

    assert response.status_code == 200
    payloads = _sse_payloads(response.text)
    assert json.loads(payloads[0])["choices"][0]["delta"]["content"] == "par"
    assert json.loads(payloads[1]) == {"error": expected}
    assert payloads[2:] == ["[DONE]"]
    assert "Error-free" not in response.text


async def test_domain_stream_does_not_write_errors_into_content(monkeypatch):
    class FailingAgent:
        llm = SimpleNamespace(streaming=True)

        def __init__(self, *_args, **_kwargs):
            pass

        async def init_assistant(self):
            return None

        async def astream(self, *_args, **_kwargs):
            yield [AIMessageChunk(content="par")]
            raise RuntimeError("boom")

    monkeypatch.setattr(
        PublishedAssistantService, "get_info", AsyncMock(return_value=SimpleNamespace(temperature=0, name="a"))
    )
    monkeypatch.setattr("bisheng.assistant.domain.services.published_assistant_service.AssistantAgent", FailingAgent)
    completion, _info = await PublishedAssistantService.complete(
        assistant_id="a" * 32,
        model=ASSISTANT_ID,
        messages=[{"role": "user", "content": "hi"}],
        stream=True,
        temperature=0,
        operator=SimpleNamespace(user_id=12),
    )
    received = []
    with pytest.raises(RuntimeError, match="boom"):
        async for item in completion.stream:
            received.append(item)
    assert len(received) == 1
    assert "boom" not in received[0]


@pytest.mark.parametrize(
    "error,http_status,status_code",
    [
        (AssistantModelNotConfigError(), 400, 10423),
        (RuntimeError("model gateway timed out"), 500, 500),
    ],
)
async def test_non_stream_error_is_a_standard_error_response(authorized, monkeypatch, error, http_status, status_code):
    class FailingAgent:
        llm = SimpleNamespace(streaming=False)

        def __init__(self, *_args, **_kwargs):
            pass

        async def init_assistant(self):
            return None

        async def run(self, *_args, **_kwargs):
            raise error

    monkeypatch.setattr(
        PublishedAssistantService, "get_info", AsyncMock(return_value=SimpleNamespace(temperature=0, name="a"))
    )
    monkeypatch.setattr("bisheng.assistant.domain.services.published_assistant_service.AssistantAgent", FailingAgent)

    response = await _post({"model": ASSISTANT_ID, "messages": [{"role": "user", "content": "hi"}], "stream": False})

    assert response.status_code == http_status
    body = response.json()
    assert body["status_code"] == status_code
    assert "choices" not in body
