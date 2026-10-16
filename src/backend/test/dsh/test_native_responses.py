"""Native protocol retains typed output through actual SDK HTTP construction and governance."""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
from openai import AsyncOpenAI
from pydantic import ValidationError

from bisheng.common.errcode.dsh import DshUnsupportedParameterError
from bisheng.dsh.domain.schemas.chat import ChatCapabilities
from bisheng.dsh.domain.schemas.conversation import ConversationHint
from bisheng.dsh.domain.schemas.reasoning import reasoning_declaration
from bisheng.dsh.domain.schemas.responses import DshResponsesRequest
from test.dsh.test_enterprise_protocol import DECLARATION
from test.dsh.test_model_service import principal, service_setup  # noqa: F401
from test.dsh.test_models_api import app_setup  # noqa: F401


def body(**changes):
    return {"model": "bisheng:42", "input": [{"role": "user", "content": "hi"}], **changes}


def result(status="completed", usage=True):
    return {
        "id": "resp_test",
        "object": "response",
        "created_at": 1,
        "status": status,
        "model": "supplier-model",
        "output": [
            {"id": "rs_test", "type": "reasoning", "summary": [], "encrypted_content": "opaque-encrypted-content"},
            {
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": "ok", "annotations": []}],
            },
        ],
        "usage": {
            "input_tokens": 10,
            "output_tokens": 2,
            "total_tokens": 12,
            "input_tokens_details": {"cached_tokens": 8},
            "output_tokens_details": {"reasoning_tokens": 1},
        }
        if usage
        else None,
    }


@pytest.mark.parametrize(
    "extra",
    [
        {"store": True},
        {"previous_response_id": "resp_other"},
        {"conversation": "foreign"},
        {"background": True},
        {"tools": [{"type": "web_search"}]},
        {"input": [{"type": "item_reference", "id": "remote"}]},
    ],
)
def test_reject_ungoverned_fields(extra):
    with pytest.raises(ValidationError):
        DshResponsesRequest(**body(**extra))


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("status", ["completed", "incomplete", "failed"])
@pytest.mark.parametrize("known_usage", [False, True])
async def test_sdk_wire_and_shared_settlement(app_setup, stream, status, known_usage):  # noqa: F811
    app, _, runtime, _, ledger = app_setup
    service = runtime.model
    captured = []
    final = result(status, known_usage)

    async def supplier(request):
        captured.append((dict(request.headers), json.loads(request.content), request.url.path))
        if not stream:
            return httpx.Response(200, json=final)
        events = [
            {
                "type": "response.created",
                "sequence_number": 0,
                "response": {**final, "status": "in_progress", "output": [], "usage": None},
            },
            {"type": f"response.{status}", "sequence_number": 1, "response": final},
        ]
        text = "".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=text)

    async with httpx.AsyncClient(transport=httpx.MockTransport(supplier)) as http:
        sdk = AsyncOpenAI(api_key="test-only", base_url="https://supplier.invalid/v1", http_client=http, max_retries=0)
        service.llm_builder = lambda *args: SimpleNamespace(
            model_name="supplier-model", llm=SimpleNamespace(root_async_client=sdk)
        )
        service.capabilities_for = lambda *args: ChatCapabilities(
            responses=True, reasoning=reasoning_declaration(DECLARATION)
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://bisheng.invalid"
        ) as client:
            response = await client.post(
                "/api/v1/dsh/responses",
                json=body(stream=stream, reasoning={"effort": "high"}),
                headers={"Authorization": "Bearer dedicated", "x-dsh-conversation-id": "conv-1"},
            )
    assert response.status_code == 200
    headers, payload, path = captured[0]
    assert path == "/v1/responses" and payload["model"] == "supplier-model"
    assert payload["store"] is False and payload["reasoning"]["effort"] == "high"
    assert payload["include"] == ["reasoning.encrypted_content"]
    assert (
        payload["prompt_cache_key"]
        == headers["session_id"]
        == ConversationHint(conversation_id="conv-1").upstream_headers(principal(), 42)["session_id"]
    )
    if stream:
        assert f"event: response.{status}" in response.text and "[DONE]" not in response.text
        assert "opaque-encrypted-content" in response.text
    else:
        assert response.json()["output"] == final["output"]
        assert response.json()["model"] == "bisheng:42"
    assert ledger.events[-1].status == (
        "USAGE_UNKNOWN" if not known_usage else "FAILED" if status == "failed" else "SUCCEEDED"
    )
    assert ledger.events[-1].total_tokens == (12 if known_usage else None)
    assert ledger.events[-1].cache_read_tokens == (8 if known_usage else None)


async def test_unnegotiated_protocol_does_not_admit(service_setup):  # noqa: F811
    service, llm, ledger, *_ = service_setup
    with pytest.raises(DshUnsupportedParameterError):
        await service.complete(principal(), DshResponsesRequest(**body()))
    assert llm.calls == 0 and not ledger.events


def test_full_tool_reasoning_history_roundtrip():
    history = [
        {"type": "reasoning", "id": "rs_test", "summary": [], "encrypted_content": "opaque"},
        {"type": "function_call", "id": "fc_test", "call_id": "call_test", "name": "lookup", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "call_test", "output": "done"},
    ]
    request = DshResponsesRequest(**body(input=history))
    assert request.model_dump(exclude_none=True)["input"] == history


@pytest.mark.parametrize("fault", ["eof", "type", "sequence", "oversize", "close", "before_start"])
async def test_native_faults_close_supplier_and_settle_once(service_setup, fault, monkeypatch):  # noqa: F811
    from bisheng.dsh.infrastructure import responses_adapter

    service, _, ledger, *_ = service_setup
    closed = []
    calls = []

    class Source:
        async def __aiter__(self):
            yield SimpleNamespace(
                model_dump=lambda **_: {
                    "type": "response.created",
                    "sequence_number": 0,
                    "response": {"model": "supplier-model"},
                }
            )
            if fault in {"eof", "close", "before_start"}:
                return
            yield SimpleNamespace(
                model_dump=lambda **_: {
                    "type": "response.web_search_call.completed" if fault == "type" else "response.output_text.delta",
                    "sequence_number": 0 if fault == "sequence" else 1,
                    "delta": "x" * 200,
                }
            )

        async def close(self):
            closed.append(True)

    @asynccontextmanager
    async def create(**_):
        calls.append(True)

        async def parse():
            return Source()

        yield SimpleNamespace(http_response=SimpleNamespace(stream=None), parse=parse)

    monkeypatch.setattr(responses_adapter, "MAX_EVENT_BYTES", 128 if fault == "oversize" else 1024)
    sdk = SimpleNamespace(responses=SimpleNamespace(with_streaming_response=SimpleNamespace(create=create)))
    service.llm_builder = lambda *args: SimpleNamespace(
        model_name="supplier-model", llm=SimpleNamespace(root_async_client=sdk)
    )
    service.capabilities_for = lambda *args: ChatCapabilities(responses=True)
    stream = await service.complete(principal(), DshResponsesRequest(**body(stream=True)))
    if fault == "before_start":
        await stream.aclose()
        assert not calls and not closed
        assert ledger.events[-1].status == "CANCELLED" and ledger.events[-1].total_tokens == 0
    elif fault == "close":
        assert "response.created" in await anext(stream)
        await stream.aclose()
        assert closed == [True] and ledger.events[-1].status == "USAGE_UNKNOWN"
    else:
        frames = [frame async for frame in stream]
        assert "event: error" in frames[-1] and "response.completed" not in "".join(frames)
        assert closed == [True] and ledger.events[-1].status == "USAGE_UNKNOWN"
    await stream.aclose()
    assert len(ledger.events) == 2  # Admission plus exactly one settlement.


async def test_raw_supplier_limit_precedes_sdk_json_decode(service_setup, monkeypatch):  # noqa: F811
    from bisheng.dsh.infrastructure import responses_adapter

    service, _, ledger, *_ = service_setup
    closed = []

    class Bytes(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"data: " + b"x" * 256  # No complete SSE event or valid JSON.

        async def aclose(self):
            closed.append(True)

    monkeypatch.setattr(responses_adapter, "MAX_RESPONSE_BYTES", 128)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                stream=Bytes(),
            )
        )
    ) as http:
        sdk = AsyncOpenAI(api_key="test-only", base_url="https://supplier.invalid/v1", http_client=http, max_retries=0)
        service.llm_builder = lambda *args: SimpleNamespace(
            model_name="supplier-model", llm=SimpleNamespace(root_async_client=sdk)
        )
        service.capabilities_for = lambda *args: ChatCapabilities(responses=True)
        stream = await service.complete(principal(), DshResponsesRequest(**body(stream=True)))
        frames = [frame async for frame in stream]
        await stream.aclose()
    assert len(frames) == 1 and "event: error" in frames[0]
    assert closed == [True] and ledger.events[-1].status == "USAGE_UNKNOWN"
