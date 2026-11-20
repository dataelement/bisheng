"""昆联知识库检索真实模式（OIDC Token Exchange、目录读取、知识检索与错误映射）契约测试。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import SecretStr

from bisheng.api.v1.endpoints import get_env
from bisheng.common.errcode.flow import (
    PlatformKnowledgeConfigurationError,
    PlatformKnowledgeNotReadyError,
    PlatformKnowledgeOutputError,
    PlatformKnowledgePermissionError,
    PlatformKnowledgeResourceError,
    PlatformKnowledgeTimeoutError,
    PlatformKnowledgeUpstreamError,
)
from bisheng.common.services.config_service import ConfigService
from bisheng.core.config.settings import PlatformKnowledgeConf, PlatformLLMConf, WorkflowConf
from bisheng.sso_sync.application.kunlian import KunlianTokenExchangeMaterial
from bisheng.workflow.application import platform_knowledge as app_platform_knowledge
from bisheng.workflow.domain.clients.kunlian_resources import SCOPE_KNOWLEDGE_RETRIEVE, SCOPE_RESOURCES_READ
from bisheng.workflow.domain.clients.platform_knowledge import build_provider
from bisheng.workflow.domain.clients.platform_knowledge_real import (
    KunlianPlatformKnowledgeClient,
    RealPlatformKnowledgeProvider,
)
from bisheng.workflow.domain.schemas.platform_knowledge import KnowledgeActor, node_configuration
from bisheng.workflow.domain.services import platform_knowledge_service as domain


def _conf(**overrides) -> PlatformKnowledgeConf:
    defaults = {
        "mode": "real",
        "policy_revision": "real-v1",
        "resource_base_url": "http://ai-gateway.comlansh.com:30001",
        "oidc_token_url": "http://ai-idp.comlansh.com:30001/oidc/token",
        "resource_audience": "moduvela-platform-resources",
    }
    defaults.update(overrides)
    return PlatformKnowledgeConf(**defaults)


def _material() -> KunlianTokenExchangeMaterial:
    return KunlianTokenExchangeMaterial(
        oidc_token_url="http://ai-idp.comlansh.com:30001/oidc/token",
        client_id="bisheng-client",
        client_secret=SecretStr("bisheng-secret"),
        subject_token=SecretStr("sso-subject-secret-token"),
    )


def _node(resource_id="kb-1", version_id="ver-1", question="温度超限怎么处理？", top_k=5):
    ref = {"resource_id": resource_id}
    if version_id is not None:
        ref["version_id"] = version_id
    return {
        "id": "retrieve_1",
        "type": "platform_knowledge_retriever",
        "group_params": [
            {
                "params": [
                    {"key": "knowledge", "value": ref},
                    {"key": "user_question", "value": {"source": "constant", "value": question}},
                    {"key": "top_k", "value": top_k},
                    {
                        "key": "retrieved_result",
                        "value": [
                            {"key": key} for key in ("retrieved_result", "retrieved_text", "citations", "hit_count")
                        ],
                    },
                ]
            }
        ],
    }


async def test_real_provider_list_supports_both_kunlian_envelopes():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/oidc/token":
            form = parse_qs(request.content.decode("utf-8"))
            assert form["scope"] == [SCOPE_RESOURCES_READ]
            assert form["audience"] == ["moduvela-platform-resources"]
            return httpx.Response(200, json={"access_token": "kb-read-token", "expires_in": 120})
        if request.url.path == "/api/platform/v1/resources":
            assert request.headers["authorization"] == "Bearer kb-read-token"
            assert request.headers["x-caller-type"] == "workflow"
            params = dict(request.url.params)
            if "types" in params:
                # 首次按统一网关 types=knowledge 失败 400，触发自动回退 resource_type=knowledge
                return httpx.Response(400, json={"status_code": 400, "data": {"reason_code": "INVALID_REQUEST"}})
            assert params["resource_type"] == "knowledge"
            return httpx.Response(
                200,
                json={
                    "code": "OK",
                    "message": "success",
                    "request_id": "req-dir-1",
                    "data": {
                        "items": [
                            {
                                "resource_type": "knowledge",
                                "resource_id": "kb-1",
                                "version_id": "ver-101",
                                "name": "设备运行手册库",
                                "use_allowed": True,
                            },
                            {
                                "resource_type": "knowledge",
                                "resource_id": "kb-denied",
                                "version_id": "ver-2",
                                "name": "无权知识库",
                                "use_allowed": False,
                            },
                        ],
                        "next_cursor": None,
                    },
                },
            )
        raise AssertionError(f"unexpected url: {request.url}")

    provider = RealPlatformKnowledgeProvider(
        _conf(),
        token_material_resolver=AsyncMock(return_value=_material()),
        transport=httpx.MockTransport(handler),
    )
    actor = KnowledgeActor(user_id=12, tenant_id=7, token_version=1, session_reference="sess-1")
    result = await provider.list_knowledge(actor, cursor=None, name=None)
    assert result == {
        "items": [
            {
                "resource_id": "kb-1",
                "version_id": "ver-101",
                "name": "设备运行手册库",
                "status": "active",
                "provider_mode": "real",
                "use_allowed": True,
            }
        ],
        "next_cursor": None,
    }
    assert len(calls) == 3


async def test_real_retrieve_executes_with_pinned_version_and_maps_citations():
    captured_scopes: list[str] = []
    captured_bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oidc/token":
            form = parse_qs(request.content.decode("utf-8"))
            captured_scopes.append(form["scope"][0])
            return httpx.Response(
                200,
                json={"access_token": "kb-retrieve-token", "expires_in": 120, "scope": SCOPE_KNOWLEDGE_RETRIEVE},
            )
        if request.url.path == "/api/platform/v1/knowledge/retrieve":
            assert request.headers["authorization"] == "Bearer kb-retrieve-token"
            assert request.headers["x-caller-type"] == "workflow"
            assert request.headers["x-trace-id"]
            assert "cookie" not in {k.lower() for k in request.headers.keys()}
            body = request.read().decode("utf-8")
            import json

            parsed = json.loads(body)
            captured_bodies.append(parsed)
            return httpx.Response(
                200,
                json={
                    "status_code": 200,
                    "status_message": "SUCCESS",
                    "data": {
                        "query_id": "query_example",
                        "permission_filtered": True,
                        "items": [
                            {
                                "chunk_id": "chunk_1",
                                "document_id": "doc_1",
                                "content": "温度超限时，先确认冷却系统状态，再记录异常时间。",
                                "score": 0.87,
                                "citation": {
                                    "title": "设备运行手册",
                                    "page": 3,
                                    "source_ref": "citation_example",
                                },
                            },
                            {
                                "chunk_id": "chunk_2",
                                "document_id": "doc_2",
                                "content": "无页码说明段落。",
                                "score": 0.72,
                                "citation": {
                                    "title": "补充规范",
                                    "page": None,
                                    "source_ref": "citation_2",
                                },
                            },
                        ],
                    },
                },
            )
        raise AssertionError(f"unexpected path: {request.url.path}")

    provider = RealPlatformKnowledgeProvider(
        _conf(),
        token_material_resolver=AsyncMock(return_value=_material()),
        transport=httpx.MockTransport(handler),
    )
    repo = SimpleNamespace(get_workflow=lambda _: {"tenant_id": 7, "flow_type": 10})
    service = domain.PlatformKnowledgeService(
        config=_conf(),
        repository=repo,
        provider=provider,
        identity_reader=AsyncMock(return_value={12: {"state": "active", "tenant_id": 7, "token_version": 1}}),
    )
    actor = KnowledgeActor(user_id=12, tenant_id=7, token_version=1, session_reference="sess-1")
    output = await service.retrieve(
        actor,
        _node(resource_id="kb-1", version_id="ver-101", top_k=50),
        lambda _: None,
        call_id="node-run-123",
        workflow_run_id="wf-session-999",
    )
    # 已指定 version_id 时，仅兑换 platform.knowledge.retrieve 权限（不再额外拉目录）
    assert captured_scopes == [SCOPE_KNOWLEDGE_RETRIEVE]
    assert captured_bodies == [
        {
            "knowledge_ref": {"resource_id": "kb-1", "version_id": "ver-101"},
            "query": "温度超限怎么处理？",
            "top_k": 50,
            "filters": {},
            "run_context": {"workflow_run_id": "wf-session-999", "node_run_id": "node-run-123"},
        }
    ]
    assert output["hit_count"] == 2
    assert output["retrieved_result"][0]["metadata"]["document_name"] == "设备运行手册"
    assert output["retrieved_result"][0]["metadata"]["location"] == "第 3 页"
    assert output["retrieved_result"][0]["metadata"]["source_ref"] == "citation_example"
    assert output["retrieved_result"][1]["metadata"].get("location") is None
    assert "设备运行手册 第 3 页\n温度超限时" in output["retrieved_text"]


async def test_real_retrieve_resolves_missing_version_id_and_requires_scope():
    def handler_missing_scope(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oidc/token":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 120, "scope": SCOPE_RESOURCES_READ})
        raise AssertionError(request.url)

    provider = RealPlatformKnowledgeProvider(
        _conf(),
        token_material_resolver=AsyncMock(return_value=_material()),
        transport=httpx.MockTransport(handler_missing_scope),
    )
    actor = KnowledgeActor(user_id=12, tenant_id=7, token_version=1)
    with pytest.raises(PlatformKnowledgePermissionError):
        await provider.retrieve(actor, "kb-1", "温度", 5, "node-1", version_id="ver-1")

    # 当节点未保存 version_id 时，retrieve 自动从目录查出当前 version_id 后调用检索
    seen_paths: list[str] = []

    def handler_lookup(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        if request.url.path == "/oidc/token":
            form = parse_qs(request.content.decode("utf-8"))
            scope = form["scope"][0]
            return httpx.Response(200, json={"access_token": f"tok-{scope}", "expires_in": 120, "scope": scope})
        if request.url.path == "/api/platform/v1/resources":
            return httpx.Response(
                200,
                json={
                    "status_code": 200,
                    "data": {
                        "data": [
                            {
                                "resource_type": "knowledge",
                                "resource_id": "kb-1",
                                "version_id": "ver-resolved",
                                "name": "知识库A",
                                "allowed_actions": ["use"],
                            }
                        ],
                        "has_more": False,
                        "next_cursor": None,
                    },
                },
            )
        if request.url.path == "/api/platform/v1/knowledge/retrieve":
            import json

            assert json.loads(request.read())["knowledge_ref"] == {"resource_id": "kb-1", "version_id": "ver-resolved"}
            return httpx.Response(200, json={"status_code": 200, "data": {"query_id": "q1", "items": []}})
        raise AssertionError(request.url)

    provider2 = RealPlatformKnowledgeProvider(
        _conf(),
        token_material_resolver=AsyncMock(return_value=_material()),
        transport=httpx.MockTransport(handler_lookup),
    )
    rows = await provider2.retrieve(actor, "kb-1", "温度", 5, "node-1")
    assert rows == []
    assert seen_paths == [
        "/oidc/token",
        "/api/platform/v1/resources",
        "/oidc/token",
        "/api/platform/v1/knowledge/retrieve",
    ]


@pytest.mark.parametrize(
    ("http_status", "body", "expected_error"),
    [
        (401, {"status_code": 401, "data": {"reason_code": "INVALID_TOKEN"}}, PlatformKnowledgePermissionError),
        (403, {"status_code": 403, "data": {"reason_code": "PERMISSION_DENIED"}}, PlatformKnowledgePermissionError),
        (404, {"status_code": 10970, "data": {"trace_id": "t-404"}}, PlatformKnowledgeResourceError),
        (409, {"status_code": 409, "data": {"reason_code": "VERSION_CONFLICT"}}, PlatformKnowledgeResourceError),
        (503, {"status_code": 503, "data": {"trace_id": "t-503"}}, PlatformKnowledgeNotReadyError),
        (504, {"status_code": 504, "data": {"trace_id": "t-504"}}, PlatformKnowledgeTimeoutError),
        (500, {"status_code": 500}, PlatformKnowledgeUpstreamError),
        (200, {"status_code": 200, "data": {"bad": True}}, PlatformKnowledgeOutputError),
    ],
)
async def test_real_retrieve_error_mappings(http_status, body, expected_error):
    client = KunlianPlatformKnowledgeClient(
        _conf(),
        transport=httpx.MockTransport(lambda _: httpx.Response(http_status, json=body)),
    )
    with pytest.raises(expected_error):
        await client.retrieve_chunks(
            SecretStr("tok"),
            resource_id="kb-1",
            version_id="ver-1",
            query="温度",
            top_k=5,
            workflow_run_id="wf-1",
            node_run_id="node-1",
        )


def test_schema_enforces_1000_char_query_and_100_top_k():
    with pytest.raises(PlatformKnowledgeConfigurationError):
        node_configuration(_node(question="x" * 1001))
    with pytest.raises(PlatformKnowledgeConfigurationError):
        node_configuration(_node(top_k=101))
    cfg = node_configuration(_node(question="x" * 1000, top_k=100))
    assert cfg.top_k == 100


def test_real_env_and_service_inherit_platform_llm_endpoints(monkeypatch):
    wf_conf = WorkflowConf(
        platform_llm=PlatformLLMConf(
            enabled=True,
            resource_base_url="http://ai-gateway.comlansh.com:30001",
            oidc_token_url="http://ai-idp.comlansh.com:30001/oidc/token",
        ),
        platform_knowledge=PlatformKnowledgeConf(mode="real"),
    )
    monkeypatch.setattr(ConfigService, "get_all_config", lambda self: {})
    monkeypatch.setattr(ConfigService, "get_workflow_conf", lambda self: wf_conf)

    env_resp = get_env()
    assert env_resp.data["workflow"]["platform_knowledge_enabled"] is True
    assert env_resp.data["workflow"]["platform_knowledge_mode"] == "real"

    svc = app_platform_knowledge.get_service()
    assert svc.config.resource_base_url == "http://ai-gateway.comlansh.com:30001"
    assert svc.config.oidc_token_url == "http://ai-idp.comlansh.com:30001/oidc/token"
    assert isinstance(build_provider(svc.config), RealPlatformKnowledgeProvider)
