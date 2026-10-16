"""Protocol extensions exercise the real governed service before supplier admission."""

import json
from types import SimpleNamespace

import httpx
import pytest
from langchain_openai import ChatOpenAI

from bisheng.common.errcode.dsh import DshUnsupportedParameterError
from bisheng.dsh.domain.schemas.chat import ChatCapabilities, DshChatRequest
from bisheng.dsh.domain.schemas.conversation import ConversationHint, parse_conversation
from bisheng.dsh.domain.schemas.reasoning import reasoning_declaration
from test.dsh.test_model_service import principal, service_setup  # noqa: F401
from test.dsh.test_models_api import app_setup  # noqa: F401

DECLARATION = {
    "reasoning_efforts": [{"id": "low", "name": "Low"}, {"id": "high", "name": "High"}],
    "reasoning_effort": "low",
}


@pytest.mark.parametrize("advanced", [False, True])
def test_declarations_use_existing_advanced_editor(advanced):
    config = {"user_kwargs": json.dumps(DECLARATION)} if advanced else DECLARATION
    assert reasoning_declaration(config).model_dump()["defaultEffort"] == "low"
    assert reasoning_declaration({}) is None
    with pytest.raises(ValueError):
        reasoning_declaration({"reasoning_effort": "high"})
    with pytest.raises(ValueError):
        reasoning_declaration({**DECLARATION, "reasoning_effort": "unknown"})


@pytest.mark.parametrize("effort", [None, "high"])
async def test_service_to_actual_sdk_wire_default_and_explicit(service_setup, effort):  # noqa: F811
    service, _, ledger, *_ = service_setup
    captured = []

    async def supplier(request):
        captured.append((dict(request.headers), json.loads(request.content)))
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(supplier)) as client:
        sdk = ChatOpenAI(
            model="test",
            api_key="test-only",
            base_url="https://supplier.invalid/v1",
            http_async_client=client,
            max_retries=0,
        )
        service.llm_builder = lambda *args: sdk
        service.capabilities_for = lambda *args: ChatCapabilities(reasoning=reasoning_declaration(DECLARATION))
        body = {"model": "bisheng:42", "messages": [{"role": "user", "content": "hi"}]}
        if effort:
            body["reasoning_effort"] = effort
        hint = ConversationHint(conversation_id="conversation-1", request_kind="compaction")
        await service.complete(principal(), DshChatRequest(**body), conversation=hint)
    headers, payload = captured[0]
    assert payload["reasoning_effort"] == (effort or "low")
    assert headers["session_id"] == hint.upstream_headers(principal(), 42)["session_id"]
    assert "conversation-1" not in headers["session_id"] and len(headers["session_id"]) == 64
    assert ledger.events[-1].total_tokens == 12


async def test_undeclared_effort_never_reaches_admission(service_setup):  # noqa: F811
    service, llm, ledger, *_ = service_setup
    with pytest.raises(DshUnsupportedParameterError):
        await service.complete(
            principal(),
            DshChatRequest(model="bisheng:42", messages=[{"role": "user", "content": "hi"}], reasoning_effort="high"),
        )
    assert llm.calls == 0 and ledger.events == []


def test_conversation_scope_is_stable_and_isolated():
    hint = ConversationHint(conversation_id="conversation-1")
    base = hint.upstream_headers(principal(), 42)
    assert base == hint.upstream_headers(principal(), 42)
    assert base != hint.upstream_headers(principal().model_copy(update={"tenant_id": "3"}), 42)
    assert base != hint.upstream_headers(principal().model_copy(update={"user_id": "21"}), 42)
    assert base != hint.upstream_headers(principal(), 43)
    # Compaction reuses the conversation's cache scope; title generation is separate.
    kinds = {
        kind: ConversationHint(conversation_id="conversation-1", request_kind=kind).upstream_headers(principal(), 42)
        for kind in ("compaction", "session-title")
    }
    assert kinds["compaction"] == base and kinds["session-title"] != base


@pytest.mark.parametrize(
    "context",
    [
        None,
        "conversation-1",
        {"request_kind": "chat"},
        {"conversation_id": ""},
        {"conversation_id": "a" * 257},
        {"conversation_id": 7},
        {"conversation_id": "a", "request_kind": "unknown"},
    ],
)
def test_invalid_audit_context_only_drops_affinity(context):
    assert parse_conversation(context) is None


def test_audit_context_uses_audit_keys():
    assert parse_conversation({"conversation_id": "c", "request_kind": "session-title", "session_origin": "main"}) == (
        ConversationHint(conversation_id="c", request_kind="session-title")
    )


async def test_audit_context_is_metadata_not_model_input(app_setup):  # noqa: F811
    app, *_ = app_setup
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://bisheng.invalid") as client:
        result = await client.post(
            "/api/v1/dsh/chat/completions",
            headers=[("Authorization", "Bearer dedicated")],
            json={
                "model": "bisheng:42",
                "messages": [{"role": "user", "content": "hi"}],
                "audit_context": {"conversation_id": "bad id with spaces is still metadata", "request_kind": "x"},
            },
        )
    # prepare_month is stubbed to fail, so reaching quota proves the body passed validation.
    assert result.status_code != 400


def test_real_model_configuration_negotiates_protocol_and_copies_chat_sdk():
    from bisheng.dsh.infrastructure.chat_adapter import DshChatAdapter
    from bisheng.dsh.infrastructure.model_capabilities import model_capabilities
    from bisheng.llm.domain.llm.llm import BishengLLM
    from bisheng.llm.domain.models import LLMModel, LLMServer

    config = {"user_kwargs": json.dumps({**DECLARATION, "use_responses_api": True})}
    model = LLMModel(id=42, server_id=7, model_name="supplier-model", model_type="llm", config=config)
    server = LLMServer(id=7, type="openai", config={"api_key": "test-only", "base_url": "https://supplier.invalid/v1"})
    capabilities = model_capabilities(model, server)
    assert capabilities.responses and capabilities.reasoning.defaultEffort == "low"
    llm = BishengLLM.get_class_instance_from_snapshot(
        model_info=model,
        server_info=server,
        app_id="test",
        app_type="dsh_desktop",
        app_name="test",
        user_id=1,
    )
    assert llm.llm.use_responses_api is True
    execution = DshChatAdapter().prepare(
        DshChatRequest(model="bisheng:42", messages=[{"role": "user", "content": "hi"}]),
        llm,
        capabilities,
    )
    assert execution.llm is not llm and execution.llm.llm.use_responses_api is False
    assert llm.llm.use_responses_api is True and model.config == config
    assert execution.parameters["reasoning_effort"] == "low"
    with pytest.raises(ValueError):
        model_capabilities(model, SimpleNamespace(type="ollama"))
    model.config = {"user_kwargs": '{"use_responses_api":"true"}'}
    with pytest.raises(ValueError):
        model_capabilities(model, server)
