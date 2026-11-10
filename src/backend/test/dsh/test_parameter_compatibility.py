"""Token aliases must reach the registered SDK adapter through the real DSH HTTP path."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from bisheng.common.errcode.dsh import DshInvalidRequestError, DshUnsupportedParameterError
from bisheng.dsh.domain.schemas.chat import ChatCapabilities, DshChatRequest
from bisheng.dsh.infrastructure.chat_adapter import DshChatAdapter
from bisheng.dsh.infrastructure.model_capabilities import model_capabilities
from bisheng.llm.domain import utils as llm_utils
from bisheng.llm.domain.llm.llm import BishengLLM
from bisheng.llm.domain.models import LLMModel, LLMServer
from test.dsh.test_model_service import service_setup  # noqa: F401
from test.dsh.test_models_api import app_setup  # noqa: F401


@pytest.mark.parametrize(
    "provider",
    [
        "openai",
        "azure_openai",
        "qwen",
        "qianfan",
        "spark",
        "tencent",
        "silicon",
        "MindIE",
        "minimax",
        "moonshot",
        "volcengine",
        "xinference",
        "llamacpp",
        "vllm",
        "deepseek",
    ],
)
def test_registered_openai_adapters_accept_completion_limit(provider):
    """AC-18: Native and compatible OpenAI clients accept the token alias."""
    caps = model_capabilities(SimpleNamespace(config={}), SimpleNamespace(type=provider))
    body = DshChatRequest(model="bisheng:42", messages=[{"role": "user", "content": "hi"}], max_completion_tokens=6500)
    execution = DshChatAdapter().prepare(body, object(), caps)
    assert caps.max_completion_tokens and execution.parameters == {"max_completion_tokens": 6500}


@pytest.mark.parametrize("provider", ["ollama", "anthropic", "zhipu", "unregistered"])
def test_unverified_adapters_still_reject_completion_limit(provider):
    """AC-18: A different SDK protocol does not inherit OpenAI parameters."""
    caps = model_capabilities(SimpleNamespace(config={}), SimpleNamespace(type=provider))
    body = DshChatRequest(model="bisheng:42", messages=[{"role": "user", "content": "hi"}], max_completion_tokens=6500)
    with pytest.raises(DshUnsupportedParameterError):
        DshChatAdapter().prepare(body, object(), caps)


@pytest.fixture
def provider_setup(app_setup, monkeypatch):  # noqa: F811
    app, _runtime, runtime, _llm, ledger = app_setup
    # Replace external legacy observers; retain the governed DSH service and ledger.
    monkeypatch.setattr(llm_utils, "bisheng_model_limit_check", AsyncMock())
    monkeypatch.setattr(llm_utils, "upload_telemetry_log", Mock())
    monkeypatch.setattr(BishengLLM, "update_model_status", AsyncMock())

    def configure(upstream, provider):
        model = LLMModel(
            id=42,
            server_id=7,
            model_name="qwen-max",
            model_type="llm",
            online=True,
            config={"user_kwargs": {"http_async_client": upstream, "max_retries": 0}},
        )
        server = LLMServer(
            id=7,
            name="Test provider",
            type=provider,
            config={"api_key": "test-only", "base_url": "https://supplier.invalid/v1"},
        )
        runtime.model.model_loader = AsyncMock(return_value=(model, server))
        runtime.model.capabilities_for = model_capabilities
        runtime.model.llm_builder = lambda model, server, principal, request: (
            BishengLLM.get_class_instance_from_snapshot(
                model_info=model,
                server_info=server,
                app_id="e2e-dsh-token-alias",
                app_type="dsh_desktop",
                app_name="e2e-dsh-token-alias",
                user_id=int(principal.user_id),
                streaming=request.stream,
                max_retries=0,
            )
        )

    return app, ledger, configure


def supplier_response(request):
    base = {"id": "chatcmpl-compat", "created": 1, "model": "qwen-max"}
    usage = {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}
    if not json.loads(request.content)["stream"]:
        return httpx.Response(
            200,
            json={
                **base,
                "object": "chat.completion",
                "usage": usage,
                "choices": [
                    {"index": 0, "message": {"role": "assistant", "content": "compat-ok"}, "finish_reason": "stop"}
                ],
            },
        )
    chunks = [
        {"choices": [{"index": 0, "delta": {"role": "assistant", "content": "compat-"}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {"content": "ok"}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
        {"choices": [], "usage": usage},
    ]
    content = "".join(
        "data: " + json.dumps({**base, "object": "chat.completion.chunk", **chunk}) + "\n\n" for chunk in chunks
    )
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=content + "data: [DONE]\n\n")


@pytest.mark.parametrize(
    "provider,wire_field", [("qwen", "max_tokens"), ("qianfan", "max_tokens"), ("openai", "max_completion_tokens")]
)
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("limit", [6500, 9000])
@pytest.mark.parametrize("input_field", ["max_tokens", "max_completion_tokens"])
async def test_http_through_bisheng_wrapper_to_supplier_wire(
    provider_setup, provider, wire_field, stream, limit, input_field
):
    """AC-18, AC-20, AC-21: Verify SDK wire, JSON/SSE output and settled usage."""
    app, ledger, configure = provider_setup
    captured = []

    async def supplier(request):
        captured.append(json.loads(request.content))
        return supplier_response(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(supplier)) as upstream:
        configure(upstream, provider)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://bisheng.invalid"
        ) as client:
            body = {
                "model": "bisheng:42",
                "messages": [{"role": "user", "content": "hi"}],
                input_field: limit,
                "stream": stream,
                "n": 1,
                "temperature": 0.2,
                "top_p": 0.8,
                "stop": ["END"],
                "audit_context": {"conversation_id": "e2e-dsh-token-alias", "request_kind": "chat"},
            }
            if stream:
                body["stream_options"] = {"include_usage": True}
            response = await client.post(
                "/api/v1/dsh/chat/completions", headers={"Authorization": "Bearer dedicated"}, json=body
            )
    assert response.status_code == 200, response.text
    assert response.headers["x-request-id"] == ledger.events[-1].request_id
    assert len(captured) == 1
    payload = captured[0]
    assert payload[wire_field] == limit
    assert ("max_completion_tokens" if wire_field == "max_tokens" else "max_tokens") not in payload
    assert payload["temperature"] == 0.2 and payload["top_p"] == 0.8 and payload["stop"] == ["END"]
    assert "audit_context" not in payload
    if provider != "openai":
        assert "prompt_cache_key" not in payload
    if stream:
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.text.endswith("data: [DONE]\n\n") and "event: error" not in response.text
        chunks = [
            json.loads(line[6:])
            for line in response.text.splitlines()
            if line.startswith("data: ") and line != "data: [DONE]"
        ]
        answer = "".join(choice["delta"].get("content", "") for chunk in chunks for choice in chunk["choices"])
        assert chunks[-1]["usage"]["total_tokens"] == 12
    else:
        assert response.headers["content-type"].startswith("application/json")
        answer = response.json()["choices"][0]["message"]["content"]
        assert response.json()["usage"]["total_tokens"] == 12
    assert answer == "compat-ok"
    assert ledger.events[-1].status == "SUCCEEDED" and ledger.events[-1].total_tokens == 12
    assert ledger.used == 102


@pytest.mark.parametrize("input_field", ["max_tokens", "max_completion_tokens"])
def test_qwen_model_output_limit_still_checked(input_field):
    """AC-18: Aliases cannot bypass the configured model output limit."""
    caps = model_capabilities(SimpleNamespace(config={}), SimpleNamespace(type="qwen"))
    body = DshChatRequest(model="bisheng:42", messages=[{"role": "user", "content": "hi"}], **{input_field: 101})
    with pytest.raises(DshInvalidRequestError):
        DshChatAdapter().prepare(body, object(), caps, max_output_tokens=100)


@pytest.mark.parametrize("field,value", [("stop", "END"), ("temperature", 0.2), ("top_p", 0.8)])
def test_explicitly_unsupported_sampling_still_rejected(field, value):
    """AC-18: Retain independent parameter capability checks."""
    caps = ChatCapabilities(**{field: False}, max_completion_tokens=True)
    body = DshChatRequest(model="bisheng:42", messages=[{"role": "user", "content": "hi"}], **{field: value})
    with pytest.raises(DshUnsupportedParameterError):
        DshChatAdapter().prepare(body, object(), caps)
