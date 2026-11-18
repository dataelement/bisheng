"""昆联平台大模型节点与客户端契约测试。"""

import json
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import SecretStr

from bisheng.common.errcode.flow import (
    PlatformLLMConfigurationError,
    PlatformLLMNotReadyError,
    PlatformLLMPermissionError,
    PlatformLLMRateLimitError,
    PlatformLLMTimeoutError,
    PlatformLLMTokenError,
)
from bisheng.core.config.settings import PlatformLLMConf
from bisheng.sso_sync.application.kunlian import KunlianTokenExchangeMaterial
from bisheng.workflow.callback.base_callback import BaseCallback
from bisheng.workflow.common.node import BaseNodeData
from bisheng.workflow.domain.clients.platform_llm import (
    SCOPE_MODEL_INVOKE,
    SCOPE_RESOURCES_READ,
    KunlianPlatformLLMClient,
)
from bisheng.workflow.domain.services.platform_llm_service import PlatformLLMService
from bisheng.workflow.graph.graph_state import GraphState
from bisheng.workflow.nodes.node_manage import NodeFactory


def _conf() -> PlatformLLMConf:
    return PlatformLLMConf(
        enabled=True,
        resource_base_url="http://ai-gateway.comlansh.com:30001",
        oidc_token_url="http://ai-idp.comlansh.com:30001/oidc/token",
        resource_audience="moduvela-platform-resources",
    )


async def test_token_exchange_and_list_models():
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if request.url.path == "/oidc/token":
            assert request.method == "POST"
            assert request.headers["authorization"].startswith("Basic ")
            assert request.headers["content-type"].startswith("application/x-www-form-urlencoded")
            form = parse_qs(request.content.decode("utf-8"))
            assert form["grant_type"] == ["urn:ietf:params:oauth:grant-type:token-exchange"]
            assert form["subject_token"] == ["sso-at-opaque"]
            assert form["subject_token_type"] == ["urn:ietf:params:oauth:token-type:access_token"]
            assert form["audience"] == ["moduvela-platform-resources"]
            assert form["scope"] == [SCOPE_RESOURCES_READ]
            return httpx.Response(
                200,
                json={"access_token": "opaque-resource-token", "token_type": "Bearer", "expires_in": 120},
            )
        if request.url.path == "/api/platform/v1/resources":
            assert request.method == "GET"
            assert request.headers["authorization"] == "Bearer opaque-resource-token"
            assert request.headers["x-caller-type"] == "workflow"
            assert "x-agent-id" not in request.headers
            assert request.url.params["types"] == "model"
            assert request.url.params["action"] == "use"
            assert request.url.params["page_size"] == "10"
            assert request.url.params["search"] == "DeepSeek"
            return httpx.Response(
                200,
                json={
                    "status_code": 200,
                    "status_message": "SUCCESS",
                    "data": {
                        "data": [
                            {
                                "resource_type": "model",
                                "resource_id": "model-1",
                                "version_id": "ver-101",
                                "name": "DeepSeek-V3",
                                "description": "desc",
                                "version": "1.0.0",
                                "status": "published",
                                "allowed_actions": ["use"],
                                "call_id": "ver-101",
                                "input_schema": None,
                                "output_schema": None,
                            }
                        ],
                        "page_size": 10,
                        "has_more": True,
                        "next_cursor": "cursor-2",
                    },
                },
            )
        raise AssertionError(f"unexpected path: {request.url}")

    client = KunlianPlatformLLMClient(_conf(), transport=httpx.MockTransport(handler))
    exchanged = await client.exchange_resource_token(
        oidc_token_url="http://ai-idp.comlansh.com:30001/oidc/token",
        client_id="bisheng-workflow-test",
        client_secret=SecretStr("secret-xyz"),
        subject_token=SecretStr("sso-at-opaque"),
        scope=SCOPE_RESOURCES_READ,
    )
    assert exchanged.access_token.get_secret_value() == "opaque-resource-token"

    page = await client.list_models(exchanged.access_token, page_size=10, search="DeepSeek")
    assert len(page.items) == 1
    assert page.items[0].call_id == "ver-101"
    assert page.has_more is True
    assert page.next_cursor == "cursor-2"
    assert len(captured) == 2


@pytest.mark.parametrize(
    ("status_code", "reason_code", "expected_exc"),
    [
        (400, "INVALID_REQUEST", PlatformLLMConfigurationError),
        (401, "INVALID_TOKEN", PlatformLLMTokenError),
        (403, "PERMISSION_DENIED", PlatformLLMPermissionError),
        (429, "RATE_LIMIT_EXCEEDED", PlatformLLMRateLimitError),
        (503, "SERVICE_UNAVAILABLE", PlatformLLMNotReadyError),
        (504, "EXECUTION_TIMEOUT", PlatformLLMTimeoutError),
    ],
)
async def test_list_models_error_mapping(status_code, reason_code, expected_exc):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            json={
                "status_code": status_code,
                "status_message": reason_code.lower(),
                "data": {"reason_code": reason_code, "trace_id": "t-1"},
            },
        )

    client = KunlianPlatformLLMClient(_conf(), transport=httpx.MockTransport(handler))
    with pytest.raises(expected_exc):
        await client.list_models(SecretStr("tok"))


async def test_get_model_version_and_forbid_latest():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/platform/v1/resources/model/m-1/versions/v-1"
        return httpx.Response(
            200,
            json={
                "code": "OK",
                "message": "success",
                "data": {"resource_id": "m-1", "version_id": "v-1", "input_schema": {"type": "object"}},
                "request_id": "req-1",
            },
        )

    client = KunlianPlatformLLMClient(_conf(), transport=httpx.MockTransport(handler))
    detail = await client.get_model_version(SecretStr("tok"), resource_id="m-1", version_id="v-1")
    assert detail["version_id"] == "v-1"

    with pytest.raises(PlatformLLMConfigurationError):
        await client.get_model_version(SecretStr("tok"), resource_id="m-1", version_id="latest")


def test_platform_llm_node_execution(monkeypatch):
    seen_payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oidc/token":
            form = parse_qs(request.content.decode("utf-8"))
            assert form["scope"] == [SCOPE_MODEL_INVOKE]
            return httpx.Response(200, json={"access_token": "invoke-tok", "expires_in": 120})
        if request.url.path == "/api/platform/v1/chat/completions":
            assert request.headers["authorization"] == "Bearer invoke-tok"
            body = json.loads(request.content.decode("utf-8"))
            seen_payloads.append(body)
            return httpx.Response(
                200,
                json={
                    "id": "chatcmpl-123",
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": "昆联模型回复：你好"}}],
                },
            )
        raise AssertionError(f"unexpected path: {request.url}")

    async def fake_material(user_id, *, session_reference=None, oidc_token_url=""):
        return KunlianTokenExchangeMaterial(
            subject_token=SecretStr("sso-user-at"),
            client_id="bisheng-workflow-test",
            client_secret=SecretStr("secret-xyz"),
            oidc_token_url="http://ai-idp.comlansh.com:30001/oidc/token",
        )

    client = KunlianPlatformLLMClient(_conf(), transport=httpx.MockTransport(handler))
    service = PlatformLLMService(config=_conf(), client=client, token_material_resolver=fake_material)

    from bisheng.workflow.application import platform_llm as app_platform_llm

    monkeypatch.setattr(app_platform_llm, "get_service", lambda: service)

    node_data = BaseNodeData.model_validate(
        {
            "id": "platform_llm_1",
            "type": "platform_llm",
            "name": "昆联大模型",
            "v": 1,
            "group_params": [
                {
                    "name": "模型设置",
                    "params": [
                        {
                            "key": "model_ref",
                            "type": "platform_model_select",
                            "value": {
                                "resource_id": "model-1",
                                "version_id": "ver-101",
                                "call_id": "ver-101",
                                "name": "DeepSeek-V3",
                                "version": "1.0.0",
                            },
                        },
                        {"key": "temperature", "type": "slide", "value": 0.3},
                    ],
                },
                {
                    "name": "提示词",
                    "params": [
                        {"key": "system_prompt", "type": "var_textarea", "value": "你是助手"},
                        {"key": "user_prompt", "type": "var_textarea", "value": "问题：{{#input_1.q#}}"},
                    ],
                },
                {
                    "name": "输出",
                    "params": [
                        {"key": "output_user", "type": "switch", "value": True},
                        {"key": "output", "type": "var", "value": [{"key": "output", "label": "output"}]},
                    ],
                },
            ],
        }
    )

    graph_state = GraphState()
    graph_state.set_variable("input_1", "q", "设备温度过高怎么办")

    node = NodeFactory.instance_node(
        node_type="platform_llm",
        node_data=node_data,
        user_id=7,
        workflow_id="wf-1",
        workflow_name="test-wf",
        graph_state=graph_state,
        target_edges=[],
        max_steps=10,
        callback=BaseCallback(),
    )
    node.run({})

    assert graph_state.get_variable("platform_llm_1", "output") == "昆联模型回复：你好"
    assert len(seen_payloads) == 1
    assert seen_payloads[0]["model"] == "ver-101"
    assert seen_payloads[0]["messages"] == [
        {"role": "system", "content": "你是助手"},
        {"role": "user", "content": "问题：设备温度过高怎么办"},
    ]
    assert seen_payloads[0]["stream"] is False
    assert seen_payloads[0]["metadata"]["workflow_run_id"] == "wf-1"
    assert seen_payloads[0]["metadata"]["node_run_id"]
