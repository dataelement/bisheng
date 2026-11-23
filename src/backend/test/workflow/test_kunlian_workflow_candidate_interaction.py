"""昆联反向调用受信协议（kunlian-workflow-candidate-v1）与 Agent 交互回调执行测试。"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from bisheng.common.errcode.flow import (
    PlatformAgentExecutionError,
    PlatformAgentUpstreamError,
)
from bisheng.core.config.settings import PlatformAgentConf
from bisheng.database.models.flow import Flow, FlowStatus
from bisheng.database.models.flow_version import FlowVersion
from bisheng.open_endpoints.api.endpoints import kunlian_workflow_candidate as candidate_api
from bisheng.sso_sync.application.kunlian import KunlianClientCredentialsMaterial
from bisheng.workflow.domain.clients.kunlian_resources import (
    KunlianInvalidTokenError,
    WorkflowExecutionIntrospection,
    introspect_workflow_execution_token,
)
from bisheng.workflow.domain.clients.platform_agent_real import RealPlatformAgentProvider
from bisheng.workflow.domain.repositories.kunlian_registration import PublishedRunRegistrationRepository
from bisheng.workflow.domain.repositories.kunlian_workflow_run import RunRepository
from bisheng.workflow.domain.schemas.kunlian_workflow_invocation import RunError, RunRequest, RunSubject
from bisheng.workflow.domain.schemas.platform_agent import (
    PUBLICATION_KEY as AGENT_PUBLICATION_KEY,
)
from bisheng.workflow.domain.schemas.platform_agent import (
    AgentReference,
    AgentVersion,
    VerifiedAgentActor,
)
from bisheng.workflow.domain.services.kunlian_descriptor import prepare_descriptor
from test.workflow.test_kunlian_workflow_publication import FLOW_ID, SCOPE, seed
from test.workflow.test_kunlian_workflow_registration_e2e import example_graph


def _graph_with_platform_agent() -> dict:
    graph = example_graph()
    agent_node = {
        "id": "platform_agent_1",
        "data": {
            "id": "platform_agent_1",
            "type": "platform_agent",
            "group_params": [
                {
                    "params": [
                        {
                            "key": "agent_ref",
                            "value": {
                                "agent_id": "agent-1",
                                "version_id": "ver-1",
                                "call_id": "release-agent-1",
                            },
                        },
                        {"key": "user_prompt", "value": "请确认设备数量"},
                        {"key": "allow_interaction", "value": True},
                    ]
                }
            ],
        },
    }
    graph["nodes"].append(agent_node)
    graph[AGENT_PUBLICATION_KEY] = {
        "binding_version": 1,
        "nodes": {
            "platform_agent_1": {
                "ref": {"agent_id": "agent-1", "version_id": "ver-1", "call_id": "release-agent-1"},
            }
        },
    }
    return graph


async def test_introspect_workflow_execution_token_validates_claims():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        return httpx.Response(
            200,
            json={
                "active": True,
                "grant_kind": "workflow_execution",
                "aud": "bisheng-workflow-test",
                "context_id": "ctx-001",
                "sub": "ext-user-1",
                "tenant_id": "ext-tenant-1",
                "workflow_version_id": "12",
            },
        )

    result = await introspect_workflow_execution_token(
        oidc_token_url="http://idp.test/oidc/token",
        client_id="bisheng-workflow-test",
        client_secret=SecretStr("sec-1"),
        token="exec-tok-1",
        expected_audience="bisheng-workflow-test",
        expected_workflow_version_id="12",
        transport=httpx.MockTransport(handler),
    )
    assert captured["url"] == "http://idp.test/oidc/introspect"
    assert captured["auth"].startswith("Basic ")
    assert result.context_id == "ctx-001"
    assert result.external_user_id == "ext-user-1"
    assert result.external_tenant_id == "ext-tenant-1"

    with pytest.raises(KunlianInvalidTokenError):
        await introspect_workflow_execution_token(
            oidc_token_url="http://idp.test/oidc/token",
            client_id="bisheng-workflow-test",
            client_secret=SecretStr("sec-1"),
            token="exec-tok-1",
            expected_workflow_version_id="99",
            transport=httpx.MockTransport(handler),
        )


def test_descriptor_and_published_schema_include_kunlian_agent_dependencies():
    graph = _graph_with_platform_agent()
    flow = SimpleNamespace(id=FLOW_ID, name="联调流程", description="desc")
    version = SimpleNamespace(id=7, description="v7")
    descriptor = prepare_descriptor(flow, version, graph, graph[AGENT_PUBLICATION_KEY], {})
    assert descriptor is not None
    assert descriptor["dependencies"] == [
        {
            "system": "kunlian",
            "resource_type": "agent",
            "resource_id": "agent-1",
            "version_id": "ver-1",
            "resource_version_id": "ver-1",
        }
    ]


def test_run_repository_supports_agent_runtime_waiting_and_operation_lookup(invocation_registration_store):
    reg = invocation_registration_store
    seed(reg)
    graph = _graph_with_platform_agent()
    with reg.transaction() as session:
        session.get(Flow, FLOW_ID).status = FlowStatus.ONLINE.value
        v = session.get(FlowVersion, 1)
        v.is_current = 1
        v.data = graph

    runs = RunRepository(PublishedRunRegistrationRepository(reg.sessions))
    body = RunRequest(workflow_id=FLOW_ID, workflow_version_id=1, input={"question": "hi"})

    # 非候选协议入口默认仍拦截 platform_agent
    with pytest.raises(RunError, match="VERSION_UNAVAILABLE"):
        runs.admit(SCOPE, 12, "op-reject", body, run_control=True)

    row, created = runs.admit(
        SCOPE,
        12,
        "op-123",
        body,
        run_control=True,
        allow_platform_agent=True,
        extra_material={"context_id": "ctx-123", "operation_key": "op-123"},
    )
    assert created
    looked_up = runs.lookup_by_operation_key(SCOPE, 12, "op-123")
    assert looked_up is not None and looked_up.session_id == row.session_id

    claim = runs.claim(SCOPE.tenant_id, row.session_id)
    assert claim is not None
    assert runs.update_agent_runtime(
        SCOPE.tenant_id,
        row.session_id,
        claim,
        {"agent_run_id": "ar-1", "remote_status": "waiting_input"},
        waiting=True,
    )
    waiting_row = runs.load(SCOPE.tenant_id, row.session_id)
    assert waiting_row.status == "WAITING_INPUT"
    assert waiting_row.material["agent_runtime"]["agent_run_id"] == "ar-1"

    assert runs.update_agent_runtime(
        SCOPE.tenant_id,
        row.session_id,
        claim,
        {"agent_run_id": "ar-1", "remote_status": "succeeded"},
        waiting=False,
    )
    assert runs.load(SCOPE.tenant_id, row.session_id).status == "RUNNING"
    assert runs.finish(SCOPE.tenant_id, row.session_id, claim, output={"result": "设备数量: 3"})
    done = runs.load(SCOPE.tenant_id, row.session_id)
    assert done.status == "SUCCEEDED" and done.output == {"result": "设备数量: 3"}


async def test_real_provider_callback_runtime_waits_and_recovers_on_succeeded():
    calls: list[tuple[str, str, str]] = []
    poll_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal poll_count
        calls.append((request.method, request.url.path, request.headers.get("X-Idempotency-Key", "")))
        if request.url.path == "/oidc/workflow-callback/token":
            return httpx.Response(200, json={"access_token": "cb-tok-1", "expires_in": 120, "scope": "platform.agent.invoke"})
        if request.url.path == "/api/platform/v1/agent-runtime/invoke":
            body = json.loads(request.content)
            assert body["model"] == "release-agent-1"
            assert body["metadata"] == {"workflow_run_id": "sess-1", "node_run_id": "node-run-1"}
            return httpx.Response(202, json={"data": {"agent_run_id": "ar-99", "status": "queued"}})
        if request.url.path == "/api/platform/v1/agent-runtime/runs/ar-99":
            poll_count += 1
            if poll_count == 1:
                return httpx.Response(200, json={"data": {"agent_run_id": "ar-99", "status": "waiting_input", "interaction_id": "int-1"}})
            return httpx.Response(200, json={"data": {"agent_run_id": "ar-99", "status": "succeeded", "result": {"content": "设备数量为 5"}}})
        return httpx.Response(404)

    async def fake_creds(*, oidc_token_url: str = ""):
        return KunlianClientCredentialsMaterial(
            client_id="cid",
            client_secret=SecretStr("csec"),
            oidc_token_url="http://idp.test/oidc/token",
            issuer="http://idp.test",
        )

    conf = PlatformAgentConf(
        mode="real",
        resource_base_url="http://gw.test",
        oidc_token_url="http://idp.test/oidc/token",
    )
    provider = RealPlatformAgentProvider(
        conf,
        callback_credentials_resolver=fake_creds,
        transport=httpx.MockTransport(handler),
        poll_sleep=AsyncMock(),
    )
    actor = VerifiedAgentActor(
        user_id=12,
        tenant_id=7,
        workflow_context_id="ctx-1",
        workflow_session_id="sess-1",
    )
    ref = AgentReference(agent_id="agent-1", version_id="ver-1", call_id="release-agent-1")
    version = AgentVersion(
        ref=ref,
        name="子Agent",
        input_schema={"type": "object", "properties": {}, "required": []},
        output_schema={"type": "object", "properties": {}, "required": []},
        call_id="release-agent-1",
        supports_async=True,
        supports_interaction=True,
    )
    observed_statuses = []
    res = await provider.invoke(
        actor,
        ref,
        {},
        "exec:node:1",
        user_prompt="请确认设备数量",
        workflow_run_id="sess-1",
        node_run_id="node-run-1",
        idempotency_key="fixed-node-start-key-123456",
        resolved_version=version,
        on_status_change=lambda snap: observed_statuses.append(snap.status),
    )
    assert res.status == "SUCCEEDED"
    assert res.agent_run_id == "ar-99"
    assert res.output["content"] == "设备数量为 5"
    assert observed_statuses == ["queued", "waiting_input", "succeeded"]
    assert [(method, path) for method, path, _ in calls] == [
        ("POST", "/oidc/workflow-callback/token"),
        ("POST", "/api/platform/v1/agent-runtime/invoke"),
        ("GET", "/api/platform/v1/agent-runtime/runs/ar-99"),
        ("GET", "/api/platform/v1/agent-runtime/runs/ar-99"),
    ]


async def test_real_provider_callback_runtime_handles_cancel_and_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oidc/workflow-callback/token":
            return httpx.Response(200, json={"access_token": "cb-tok-1", "expires_in": 120, "scope": "platform.agent.invoke"})
        if request.url.path == "/api/platform/v1/agent-runtime/invoke":
            return httpx.Response(202, json={"data": {"agent_run_id": "ar-fail", "status": "queued"}})
        if request.url.path == "/api/platform/v1/agent-runtime/runs/ar-fail":
            return httpx.Response(200, json={"request_id": "req-err-1", "data": {"agent_run_id": "ar-fail", "status": "failed", "error_code": "AGENT_ERR"}})
        return httpx.Response(404)

    async def fake_creds(*, oidc_token_url: str = ""):
        return KunlianClientCredentialsMaterial(
            client_id="cid",
            client_secret=SecretStr("csec"),
            oidc_token_url="http://idp.test/oidc/token",
            issuer="http://idp.test",
        )

    conf = PlatformAgentConf(mode="real", resource_base_url="http://gw.test", oidc_token_url="http://idp.test/oidc/token")
    provider = RealPlatformAgentProvider(
        conf,
        callback_credentials_resolver=fake_creds,
        transport=httpx.MockTransport(handler),
        poll_sleep=AsyncMock(),
    )
    actor = VerifiedAgentActor(user_id=12, tenant_id=7, workflow_context_id="ctx-1", workflow_session_id="sess-1")
    ref = AgentReference(agent_id="agent-1", version_id="ver-1", call_id="release-agent-1")
    version = AgentVersion(
        ref=ref,
        name="子Agent",
        input_schema={"type": "object", "properties": {}, "required": []},
        output_schema={"type": "object", "properties": {}, "required": []},
        call_id="release-agent-1",
    )

    with pytest.raises(PlatformAgentUpstreamError):
        await provider.invoke(
            actor,
            ref,
            {},
            user_prompt="hi",
            idempotency_key="fixed-key-1234567890",
            resolved_version=version,
        )

    with pytest.raises(PlatformAgentExecutionError):
        await provider.invoke(
            actor,
            ref,
            {},
            user_prompt="hi",
            idempotency_key="fixed-key-1234567890",
            resolved_version=version,
            existing_agent_run_id="ar-fail",
            is_cancelled=lambda: True,
        )


async def test_candidate_endpoints_capabilities_invoke_lookup_session_cancel(
    invocation_registration_store, monkeypatch
):
    reg = invocation_registration_store
    seed(reg)
    graph = _graph_with_platform_agent()
    with reg.transaction() as session:
        session.get(Flow, FLOW_ID).status = FlowStatus.ONLINE.value
        v = session.get(FlowVersion, 1)
        v.is_current = 1
        v.data = graph

    runs = RunRepository(PublishedRunRegistrationRepository(reg.sessions))
    dispatched = []

    async def fake_resolve(_subject):
        return SimpleNamespace(user_id=12, tenant_id=7)

    async def fake_auth(_request, *, expected_workflow_version_id=None):
        subject = RunSubject(
            tenant_id=7,
            connection_id=SCOPE.connection_id,
            user_id=12,
            identity_connection_id=SCOPE.connection_id,
            external_tenant_id="ext-t",
            external_user_id="ext-u",
        )
        introspected = WorkflowExecutionIntrospection(
            context_id="ctx-99",
            external_user_id="ext-u",
            external_tenant_id="ext-t",
            workflow_version_id="1",
        )
        return subject, introspected

    from bisheng.workflow.application import kunlian_workflow_invocation as inv_mod
    from bisheng.workflow.application.kunlian_runtime import create_kunlian_runtime_service

    monkeypatch.setattr(inv_mod, "require_business_action", AsyncMock())
    monkeypatch.setattr(candidate_api, "_authenticate_candidate", fake_auth)
    service = create_kunlian_runtime_service(
        repository=runs,
        resolve_user=fake_resolve,
        dispatch=lambda *args: dispatched.append(args),
    )
    monkeypatch.setattr(candidate_api, "_build_candidate_runtime_service", AsyncMock(return_value=service))

    app = FastAPI()
    app.include_router(candidate_api.router)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        cap = await client.get("/api/v2/workflow/capabilities")
        assert cap.status_code == 200
        assert cap.json()["data"] == {
            "protocol_version": "kunlian-workflow-candidate-v1",
            "fixed_workflow_version": True,
            "operation_lookup": True,
        }

        inv = await client.post(
            "/api/v2/workflow/invoke",
            headers={"Authorization": "Bearer tok", "X-Idempotency-Key": "op-key-001"},
            json={"workflow_id": FLOW_ID, "workflow_version_id": 1, "input": {"question": "hi"}},
        )
        assert inv.status_code == 202
        sess_id = inv.json()["data"]["session_id"]
        assert inv.json()["data"]["context_id"] == "ctx-99"
        assert len(dispatched) == 1

        # 幂等回查
        lookup = await client.get("/api/v2/workflow/invocations/op-key-001", headers={"Authorization": "Bearer tok"})
        assert lookup.status_code == 200
        assert lookup.json()["data"]["session_id"] == sess_id

        # 查询状态
        sess = await client.get(f"/api/v2/workflow/sessions/{sess_id}", headers={"Authorization": "Bearer tok"})
        assert sess.status_code == 200
        assert sess.json()["data"]["status"] == "queued"

        # 取消
        cancelled = await client.post(
            f"/api/v2/workflow/sessions/{sess_id}/cancel",
            headers={"Authorization": "Bearer tok"},
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["data"]["status"] == "cancelled"
        assert cancelled.json()["data"]["cancel_state"] == "CONFIRMED"


async def test_worker_runtime_service_authorizes_candidate_run_without_api_key_credential(monkeypatch):
    from bisheng.common.services import config_service
    from bisheng.core.config.settings import WorkflowConf
    from bisheng.open_api.application import kunlian_access
    from bisheng.user.application import runtime_identity
    from bisheng.workflow.application import kunlian_runtime as runtime_mod
    from bisheng.workflow.application import kunlian_workflow_invocation as inv_mod

    monkeypatch.setattr(config_service.ConfigService, "get_workflow_conf", lambda _self: WorkflowConf())
    monkeypatch.setattr(inv_mod, "require_business_action", AsyncMock())
    monkeypatch.setattr(
        runtime_identity,
        "read_current_person_facts",
        AsyncMock(return_value={12: {"state": "active", "tenant_id": 7}}),
    )

    revalidate_calls = 0

    async def fail_revalidate(_subject, *, app=None):
        nonlocal revalidate_calls
        revalidate_calls += 1
        raise RunError("FORBIDDEN")

    monkeypatch.setattr(kunlian_access, "revalidate_kunlian_subject", fail_revalidate)

    service = await runtime_mod.get_kunlian_runtime_service()
    monkeypatch.setattr(service.repository, "verify_target", lambda _tid, _wid: None)

    candidate_row = SimpleNamespace(
        tenant_id=7,
        connection_id="kunlian",
        user_id=12,
        workflow_id=FLOW_ID,
        material={
            "kunlian_protocol": "kunlian-workflow-candidate-v1",
            "context_id": "ctx-worker-1",
            "kunlian_identity": {
                "tenant_id": 7,
                "connection_id": "kunlian",
                "user_id": 12,
                "credential_id": None,
                "identity_connection_id": "kunlian",
                "external_tenant_id": "ext-t",
                "external_user_id": "ext-u",
                "policy_revision": None,
            },
        },
    )
    user = await service.authorize_run(candidate_row)
    assert (user.user_id, user.tenant_id) == (12, 7)
    assert revalidate_calls == 0

    formal_missing_cred = SimpleNamespace(
        tenant_id=7,
        connection_id="kunlian",
        user_id=12,
        workflow_id=FLOW_ID,
        material={
            "kunlian_identity": {
                "tenant_id": 7,
                "connection_id": "kunlian",
                "user_id": 12,
                "credential_id": None,
            }
        },
    )
    with pytest.raises(RunError, match="FORBIDDEN"):
        await service.authorize_run(formal_missing_cred)
    assert revalidate_calls == 1


async def test_callback_token_exchange_retries_briefly_when_session_unconfirmed():
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        if request.url.path == "/oidc/workflow-callback/token":
            attempts += 1
            if attempts == 1:
                return httpx.Response(401, json={"error": "session_not_ready"})
            return httpx.Response(200, json={"access_token": "cb-tok-retry", "expires_in": 120, "scope": "platform.agent.invoke"})
        if request.url.path == "/api/platform/v1/agent-runtime/invoke":
            return httpx.Response(202, json={"data": {"agent_run_id": "ar-retry", "status": "succeeded", "result": {"content": "已确认"}}})
        return httpx.Response(404)

    async def fake_creds(*, oidc_token_url: str = ""):
        return KunlianClientCredentialsMaterial(
            client_id="cid",
            client_secret=SecretStr("csec"),
            oidc_token_url="http://idp.test/oidc/token",
            issuer="http://idp.test",
        )

    conf = PlatformAgentConf(mode="real", resource_base_url="http://gw.test", oidc_token_url="http://idp.test/oidc/token")
    sleep_mock = AsyncMock()
    provider = RealPlatformAgentProvider(
        conf,
        callback_credentials_resolver=fake_creds,
        transport=httpx.MockTransport(handler),
        poll_sleep=sleep_mock,
    )
    actor = VerifiedAgentActor(user_id=12, tenant_id=7, workflow_context_id="ctx-1", workflow_session_id="sess-1")
    ref = AgentReference(agent_id="agent-1", version_id="ver-1", call_id="release-agent-1")
    version = AgentVersion(
        ref=ref,
        name="子Agent",
        input_schema={"type": "object", "properties": {}, "required": []},
        output_schema={"type": "object", "properties": {}, "required": []},
        call_id="release-agent-1",
    )

    res = await provider.invoke(
        actor,
        ref,
        {},
        user_prompt="确认",
        idempotency_key="fixed-retry-key-123456",
        resolved_version=version,
    )
    assert attempts == 2
    assert sleep_mock.await_count == 1
    assert res.status == "SUCCEEDED"
    assert res.output["content"] == "已确认"
