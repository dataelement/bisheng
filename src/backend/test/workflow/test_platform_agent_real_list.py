"""昆联平台已发布 Agent 列表与固定版本详情真实模式契约测试。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs

import httpx
import pytest
from loguru import logger
from pydantic import SecretStr

from bisheng.api.v1.endpoints import get_env
from bisheng.common.errcode.flow import (
    PlatformAgentBadRequestError,
    PlatformAgentExecutionError,
    PlatformAgentNotReadyError,
    PlatformAgentPermissionError,
    PlatformAgentRateLimitError,
    PlatformAgentTokenError,
    PlatformAgentUnknownError,
    PlatformAgentUpstreamError,
    PlatformAgentVersionError,
)
from bisheng.common.services.config_service import ConfigService
from bisheng.core.config.settings import PlatformAgentConf, PlatformLLMConf, WorkflowConf
from bisheng.sso_sync.application.kunlian import KunlianTokenExchangeMaterial
from bisheng.workflow.application import platform_agent as app_platform_agent
from bisheng.workflow.domain.clients.kunlian_resources import SCOPE_AGENT_INVOKE, SCOPE_RESOURCES_READ
from bisheng.workflow.domain.clients.platform_agent import build_provider
from bisheng.workflow.domain.clients.platform_agent_real import (
    KunlianPlatformAgentClient,
    RealPlatformAgentProvider,
)
from bisheng.workflow.domain.schemas.platform_agent import AgentReference, VerifiedAgentActor
from bisheng.workflow.domain.services import platform_agent_service as domain


def _conf(**overrides) -> PlatformAgentConf:
    defaults = {
        "mode": "real",
        "policy_revision": "real-v1",
        "resource_base_url": "http://ai-gateway.comlansh.com:30001",
        "oidc_token_url": "http://ai-idp.comlansh.com:30001/oidc/token",
        "resource_audience": "moduvela-platform-resources",
    }
    defaults.update(overrides)
    return PlatformAgentConf(**defaults)


def _material() -> KunlianTokenExchangeMaterial:
    return KunlianTokenExchangeMaterial(
        oidc_token_url="http://ai-idp.comlansh.com:30001/oidc/token",
        client_id="bisheng-client",
        client_secret=SecretStr("bisheng-secret"),
        subject_token=SecretStr("sso-subject-secret-token"),
    )


async def test_real_provider_token_exchange_and_multi_version_agent_list():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/oidc/token":
            assert request.method == "POST"
            assert request.headers["authorization"].startswith("Basic ")
            assert "cookie" not in {k.lower() for k in request.headers.keys()}
            form = parse_qs(request.content.decode("utf-8"))
            assert form["grant_type"] == ["urn:ietf:params:oauth:grant-type:token-exchange"]
            assert form["subject_token"] == ["sso-subject-secret-token"]
            assert form["subject_token_type"] == ["urn:ietf:params:oauth:token-type:access_token"]
            assert form["audience"] == ["moduvela-platform-resources"]
            assert form["scope"] == [SCOPE_RESOURCES_READ]
            return httpx.Response(200, json={"access_token": "kunlian-agent-read-token", "expires_in": 300})
        if request.url.path == "/api/platform/v1/resources":
            assert request.headers["authorization"] == "Bearer kunlian-agent-read-token"
            assert request.headers["x-caller-type"] == "workflow"
            params = dict(request.url.params)
            assert params == {
                "types": "agent",
                "action": "use",
                "page_size": "20",
                "search": "财务",
                "cursor": "cur-1",
            }
            return httpx.Response(
                200,
                json={
                    "status_code": 200,
                    "status_message": "SUCCESS",
                    "data": {
                        "data": [
                            {
                                "resource_type": "agent",
                                "resource_id": "agent-finance-001",
                                "version_id": "ver-101",
                                "name": "财务助手",
                                "description": "企业报销",
                                "version": "1.0.0",
                                "status": "published",
                                "allowed_actions": ["use"],
                                "call_id": "agent:agent-finance-001:ver-101",
                                "input_schema": None,
                                "output_schema": None,
                            },
                            {
                                "resource_type": "agent",
                                "resource_id": "agent-finance-001",
                                "version_id": "ver-102",
                                "name": "财务助手",
                                "description": "企业报销 V2",
                                "version": "2.0.0",
                                "status": "published",
                                "allowed_actions": ["use"],
                                "call_id": "agent:agent-finance-001:ver-102",
                                "input_schema": None,
                                "output_schema": None,
                            },
                        ],
                        "page_size": 20,
                        "has_more": True,
                        "next_cursor": "cur-2",
                    },
                },
            )
        raise AssertionError(f"unexpected request {request.url}")

    transport = httpx.MockTransport(handler)

    async def resolver(user_id: int, *, session_reference=None, oidc_token_url=""):
        assert user_id == 12
        assert session_reference == "sess-1"
        return _material()

    provider = RealPlatformAgentProvider(
        _conf(),
        token_material_resolver=resolver,
        transport=transport,
    )
    actor = VerifiedAgentActor(user_id=12, tenant_id=7, token_version=0, session_reference="sess-1")
    result = await provider.list_agents(actor, "cur-1", page_size=20, search="  财务  ")

    assert result["provider_mode"] == "real"
    assert result["policy_revision"] == "real-v1"
    assert result["has_more"] is True
    assert result["next_cursor"] == "cur-2"
    assert len(result["items"]) == 2
    assert result["data"] == [
        {
            "agent_id": "agent-finance-001",
            "name": "财务助手",
            "description": "企业报销",
            "versions": ["ver-101", "ver-102"],
            "version_items": [
                {
                    "version_id": "ver-101",
                    "version": "1.0.0",
                    "call_id": "agent:agent-finance-001:ver-101",
                    "name": "财务助手",
                    "description": "企业报销",
                    "status": "published",
                    "allowed_actions": ["use"],
                },
                {
                    "version_id": "ver-102",
                    "version": "2.0.0",
                    "call_id": "agent:agent-finance-001:ver-102",
                    "name": "财务助手",
                    "description": "企业报销 V2",
                    "status": "published",
                    "allowed_actions": ["use"],
                },
            ],
        }
    ]


async def test_real_list_agents_preserves_empty_page_when_has_more_true():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "cursor" not in request.url.params
        return httpx.Response(
            200,
            json={
                "status_code": 200,
                "status_message": "SUCCESS",
                "data": {
                    "data": [],
                    "page_size": 20,
                    "has_more": True,
                    "next_cursor": "opaque-cursor-next",
                },
            },
        )

    client = KunlianPlatformAgentClient(_conf(), transport=httpx.MockTransport(handler))
    page = await client.list_agents(SecretStr("tok"), page_size=20)
    assert page.items == []
    assert page.has_more is True
    assert page.next_cursor == "opaque-cursor-next"


@pytest.mark.parametrize(
    ("http_status", "reason_code", "expected_error"),
    [
        (400, "INVALID_REQUEST", PlatformAgentBadRequestError),
        (401, "INVALID_TOKEN", PlatformAgentTokenError),
        (403, "PERMISSION_DENIED", PlatformAgentPermissionError),
        (429, "RATE_LIMIT_EXCEEDED", PlatformAgentRateLimitError),
        (502, "UPSTREAM_ERROR", PlatformAgentUpstreamError),
        (503, "SERVICE_UNAVAILABLE", PlatformAgentNotReadyError),
        (504, "EXECUTION_TIMEOUT", PlatformAgentUnknownError),
    ],
)
async def test_real_list_agents_maps_errors_and_logs_reason_code_trace_id(
    http_status, reason_code, expected_error
):
    captured_logs: list[str] = []
    sink_id = logger.add(lambda msg: captured_logs.append(str(msg)), level="WARNING")
    try:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                http_status,
                headers={"X-Trace-ID": f"hdr-{reason_code}"},
                json={
                    "status_code": http_status,
                    "status_message": "ERROR",
                    "data": {
                        "reason_code": f"{reason_code}\nINJECTED",
                        "trace_id": "trace-xyz-123",
                    },
                },
            )

        client = KunlianPlatformAgentClient(_conf(), transport=httpx.MockTransport(handler))
        with pytest.raises(expected_error):
            await client.list_agents(SecretStr("super-secret-resource-token"), page_size=20)
    finally:
        logger.remove(sink_id)

    joined = "\n".join(captured_logs)
    assert reason_code in joined
    assert "trace-xyz-123" in joined
    assert "INJECTED\n" not in joined
    assert "super-secret-resource-token" not in joined


async def test_fixed_version_detail_parses_kunlian_envelope_and_falls_back_null_schemas():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/platform/v1/resources/agent/agent-finance-001/versions/ver-101"
        return httpx.Response(
            200,
            json={
                "code": "OK",
                "message": "success",
                "request_id": "req-1",
                "data": {
                    "resource_type": "agent",
                    "resource_id": "agent-finance-001",
                    "version_id": "ver-101",
                    "name": "财务助手",
                    "description": "企业报销",
                    "version": "1.0.0",
                    "status": "published",
                    "call_id": "agent:agent-finance-001:ver-101",
                    "allowed_actions": ["use"],
                    "input_schema": None,
                    "output_schema": None,
                },
            },
        )

    client = KunlianPlatformAgentClient(_conf(), transport=httpx.MockTransport(handler))
    ver = await client.get_agent_version(
        SecretStr("tok"),
        resource_id="agent-finance-001",
        version_id="ver-101",
    )
    assert ver.ref.agent_id == "agent-finance-001"
    assert ver.ref.version_id == "ver-101"
    assert ver.call_id == "agent:agent-finance-001:ver-101"
    assert ver.version == "1.0.0"
    assert ver.input_schema == {"type": "object", "properties": {}, "required": []}
    assert ver.output_schema == {"type": "object", "properties": {}, "required": []}
    assert ver.can_use is True

    with pytest.raises(PlatformAgentVersionError):
        await client.get_agent_version(SecretStr("tok"), resource_id="agent-finance-001", version_id="latest")


def test_unconfigured_real_provider_raises_not_ready():
    with pytest.raises(PlatformAgentNotReadyError):
        build_provider(PlatformAgentConf(mode="real", resource_base_url=""))


async def test_real_provider_invoke_sync_chat_completion_and_wraps_empty_schema():
    import json as _json

    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if request.url.path == "/oidc/token":
            form = parse_qs(request.content.decode("utf-8"))
            scope = form["scope"][0]
            token_value = "agent-invoke-tok" if scope == SCOPE_AGENT_INVOKE else "agent-read-tok"
            return httpx.Response(200, json={"access_token": token_value, "expires_in": 120, "scope": scope})
        if request.url.path == "/api/platform/v1/resources/agent/a43f6f70/versions/release-babc":
            assert request.headers["authorization"] == "Bearer agent-read-tok"
            return httpx.Response(
                200,
                json={
                    "code": "OK",
                    "data": {
                        "resource_type": "agent",
                        "resource_id": "a43f6f70",
                        "version_id": "release-babc",
                        "name": "毕昇联调 Agent",
                        "call_id": "release-babc",
                        "status": "PUBLISHED",
                        "allowed_actions": ["use"],
                        "input_schema": None,
                        "output_schema": None,
                    },
                },
            )
        if request.url.path == "/api/platform/v1/chat/completions":
            assert request.method == "POST"
            assert request.headers["authorization"] == "Bearer agent-invoke-tok"
            assert request.headers["x-caller-type"] == "workflow"
            assert request.headers["x-trace-id"]
            idem = request.headers["x-idempotency-key"]
            assert 16 <= len(idem) <= 128 and " " not in idem
            assert "cookie" not in {k.lower() for k in request.headers.keys()}
            body = _json.loads(request.content.decode("utf-8"))
            assert body == {
                "model": "release-babc",
                "messages": [{"role": "user", "content": "请执行毕昇联调测试。"}],
                "stream": False,
                "metadata": {"workflow_run_id": "wf-sess-001", "node_run_id": "node-run-001"},
            }
            return httpx.Response(
                200,
                headers={"X-Trace-ID": request.headers["x-trace-id"], "X-Request-ID": "req-kl-001"},
                json={
                    "id": "chatcmpl-kl-001",
                    "object": "chat.completion",
                    "model": "release-babc",
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": "毕昇联调通过"},
                        }
                    ],
                },
            )
        raise AssertionError(f"unexpected path {request.url.path}")

    async def resolver(user_id: int, *, session_reference=None, oidc_token_url=""):
        return _material()

    provider = build_provider(_conf())
    assert isinstance(provider, RealPlatformAgentProvider)
    real_provider = RealPlatformAgentProvider(
        _conf(),
        token_material_resolver=resolver,
        transport=httpx.MockTransport(handler),
    )
    res = await real_provider.invoke(
        VerifiedAgentActor(12, 7, session_reference="sess-1"),
        AgentReference(agent_id="a43f6f70", version_id="release-babc"),
        {},
        "exec1:pa_1:0",
        user_prompt="请执行毕昇联调测试。",
        workflow_run_id="wf-sess-001",
        node_run_id="node-run-001",
        idempotency_key="idem-fixed-key-0001",
    )
    assert res.status == "SUCCEEDED"
    assert res.agent_run_id == "chatcmpl-kl-001"
    assert res.ref == AgentReference(agent_id="a43f6f70", version_id="release-babc")
    assert res.output == {
        "content": "毕昇联调通过",
        "id": "chatcmpl-kl-001",
        "model": "release-babc",
        "finish_reason": "stop",
    }
    assert [req.url.path for req in captured] == [
        "/oidc/token",
        "/api/platform/v1/resources/agent/a43f6f70/versions/release-babc",
        "/oidc/token",
        "/api/platform/v1/chat/completions",
    ]


async def test_real_provider_invoke_rejects_token_missing_agent_invoke_scope():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oidc/token":
            return httpx.Response(200, json={"access_token": "tok-only-read", "expires_in": 120, "scope": "openid"})
        raise AssertionError("chat completions must not be called without platform.agent.invoke scope")

    async def resolver(user_id: int, *, session_reference=None, oidc_token_url=""):
        return _material()

    from bisheng.workflow.domain.schemas.platform_agent import AgentVersion

    provider = RealPlatformAgentProvider(
        _conf(),
        token_material_resolver=resolver,
        transport=httpx.MockTransport(handler),
    )
    version = AgentVersion(
        ref=AgentReference(agent_id="a43f6f70", version_id="release-babc"),
        name="Agent",
        call_id="release-babc",
        input_schema={"type": "object", "properties": {}, "required": []},
        output_schema={"type": "object", "properties": {}, "required": []},
        available=True,
        can_use=True,
    )
    with pytest.raises(PlatformAgentPermissionError):
        await provider.invoke(
            VerifiedAgentActor(12, 7),
            AgentReference(agent_id="a43f6f70", version_id="release-babc"),
            {},
            "exec1:pa_1:0",
            user_prompt="hello",
            resolved_version=version,
        )


@pytest.mark.parametrize(
    ("http_status", "error_code", "expected_error"),
    [
        (401, "invalid_token", PlatformAgentTokenError),
        (403, "permission_denied", PlatformAgentPermissionError),
        (409, "idempotency_in_progress", PlatformAgentExecutionError),
        (409, "idempotency_conflict", PlatformAgentExecutionError),
        (429, "rate_limit_exceeded", PlatformAgentRateLimitError),
        (503, "service_unavailable", PlatformAgentNotReadyError),
        (504, "execution_timeout", PlatformAgentUnknownError),
    ],
)
async def test_real_invoke_chat_completion_maps_kunlian_error_codes(http_status, error_code, expected_error):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            http_status,
            headers={"X-Trace-ID": "trace-invoke-err", "X-Request-ID": "req-invoke-err"},
            json={"error": {"code": error_code, "message": "failed"}},
        )

    client = KunlianPlatformAgentClient(_conf(), transport=httpx.MockTransport(handler))
    with pytest.raises(expected_error):
        await client.invoke_chat_completion(
            SecretStr("tok"),
            call_id="release-babc",
            messages=[{"role": "user", "content": "hi"}],
            workflow_run_id="wf-1",
            node_run_id="nd-1",
            idempotency_key="idem-fixed-key-0001",
        )


async def test_real_provider_invoke_parses_structured_output_when_schema_defined():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oidc/token":
            return httpx.Response(
                200,
                json={"access_token": "agent-invoke-tok", "expires_in": 120, "scope": SCOPE_AGENT_INVOKE},
            )
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-struct-1",
                "object": "chat.completion",
                "model": "release-struct",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": '{"summary": "done", "score": 100}'},
                    }
                ],
            },
        )

    async def resolver(user_id: int, *, session_reference=None, oidc_token_url=""):
        return _material()

    from bisheng.workflow.domain.schemas.platform_agent import AgentVersion

    provider = RealPlatformAgentProvider(
        _conf(),
        token_material_resolver=resolver,
        transport=httpx.MockTransport(handler),
    )
    version = AgentVersion(
        ref=AgentReference(agent_id="agent-s", version_id="ver-s"),
        name="Struct Agent",
        call_id="release-struct",
        input_schema={"type": "object", "properties": {}, "required": []},
        output_schema={
            "type": "object",
            "properties": {"summary": {"type": "string"}, "score": {"type": "integer"}},
            "required": ["summary", "score"],
        },
        available=True,
        can_use=True,
    )
    res = await provider.invoke(
        VerifiedAgentActor(12, 7),
        version.ref,
        {},
        "exec1:pa_1:0",
        user_prompt="evaluate",
        resolved_version=version,
    )
    assert res.output == {"summary": "done", "score": 100}


async def test_platform_agent_conf_and_env_fallback_to_platform_llm(monkeypatch):
    wf_conf = WorkflowConf(
        platform_agent=PlatformAgentConf(mode="real", resource_base_url=""),
        platform_llm=PlatformLLMConf(
            enabled=True,
            resource_base_url="http://ai-gateway.comlansh.com:30001",
            oidc_token_url="http://ai-idp.comlansh.com:30001/oidc/token",
        ),
    )
    monkeypatch.setattr(ConfigService, "get_all_config", lambda _self: {})
    monkeypatch.setattr(ConfigService, "get_workflow_conf", lambda _self: wf_conf)

    resolved = app_platform_agent._resolve_platform_agent_conf()
    assert resolved.resource_base_url == "http://ai-gateway.comlansh.com:30001"
    assert resolved.oidc_token_url == "http://ai-idp.comlansh.com:30001/oidc/token"

    env_resp = get_env()
    assert env_resp.data["workflow"]["platform_agent_enabled"] is True
    assert env_resp.data["workflow"]["platform_agent_mode"] == "real"


async def test_service_validate_graph_accepts_enriched_agent_reference_metadata(monkeypatch):
    class FakeRepo:
        def get_workflow(self, flow_id):
            return {"id": flow_id, "tenant_id": 7, "flow_type": 10}

    class FakeProvider:
        async def get_version(self, actor, ref):
            assert ref.agent_id == "agent-1"
            assert ref.version_id == "ver-1"
            from bisheng.workflow.domain.schemas.platform_agent import AgentVersion

            return AgentVersion(
                ref=AgentReference(agent_id="agent-1", version_id="ver-1"),
                name="财务助手",
                call_id="agent:agent-1:ver-1",
                version="1.0.0",
                input_schema={"type": "object", "properties": {}, "required": []},
                output_schema={"type": "object", "properties": {}, "required": []},
                available=True,
                can_use=True,
            )

        async def check_use(self, actor, ref):
            return None

    async def fake_identity(ids):
        return {12: {"state": "active", "tenant_id": 7, "token_version": 1}}

    monkeypatch.setattr(domain, "require_business_action", AsyncMock())
    service = domain.PlatformAgentService(
        config=_conf(),
        repository=FakeRepo(),
        provider=FakeProvider(),
        identity_reader=fake_identity,
    )
    graph = {
        "nodes": [
            {
                "id": "pa-1",
                "data": {
                    "id": "pa-1",
                    "type": "platform_agent",
                    "group_params": [
                        {
                            "params": [
                                {
                                    "key": "agent_ref",
                                    "value": {
                                        "agent_id": "agent-1",
                                        "version_id": "ver-1",
                                        "call_id": "agent:agent-1:ver-1",
                                        "name": "财务助手",
                                        "version": "1.0.0",
                                    },
                                },
                                {"key": "input_bindings", "value": {}},
                            ]
                        }
                    ],
                },
            }
        ],
        "edges": [],
    }
    res = await service.validate_graph(SimpleNamespace(user_id=12, tenant_id=7), "wf-1", graph)
    assert res["valid"] is True
    assert res["nodes"]["pa-1"]["ref"] == {"agent_id": "agent-1", "version_id": "ver-1"}
