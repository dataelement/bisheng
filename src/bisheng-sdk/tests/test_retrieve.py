"""retrieve：两把凭据、门面入参出参、fail-closed（AC-03 / 08 / 11 / 12 / 14 / 15 / 16 / 17 / 18 / 19）。

**这里断言的是 F055 已落地的托管运行契约**（`open_endpoints/api/endpoints/filelib.py`
的 `HOSTED_APP_ACTOR_KIND` 分支）：一次检索带两把凭据——`Authorization: Bearer`
是**应用**的运行期凭据（平台据此取白名单），`X-BiSheng-Access-Token` 是**访问者**
的凭据（平台据此确立访问用户）。没有访问者头就没有访问用户，检索被直接拒绝，
**没有 owner 可以兜底**。
"""

from __future__ import annotations

import inspect

import httpx
import pytest

from bisheng_sdk import auth, retrieve
from bisheng_sdk.errors import (
    AppCredentialMissingError,
    CapabilityNotDeclaredError,
    CapabilityRevokedError,
    PermissionEvaluationError,
    PlatformRefusedError,
    PlatformTooOldError,
    ScopeMissingError,
    TargetUnreachableError,
    VisitorCredentialMissingError,
    VisitorCredentialRejectedError,
)
from tests.helpers import platform_mock as pm


@pytest.fixture
def wired(mock_transport, platform_env, app_token_env):
    """平台就绪：版本探测通过 + 检索按给定响应作答。"""

    def install(retrieve_response=None):
        retrieve_response = retrieve_response or pm.json_response(
            200, {"status_code": 200, "status_message": "SUCCESS", "data": pm.retrieve_payload()}
        )
        return mock_transport(
            pm.routes(
                {
                    pm.VERSIONS_PATH: pm.json_response(
                        200, {"status_code": 200, "status_message": "", "data": pm.versions_payload()}
                    ),
                    pm.RETRIEVE_PATH: retrieve_response,
                }
            )
        )

    return install


def _retrieve_request(transport) -> httpx.Request:
    return next(request for request in transport.requests if request.url.path == pm.RETRIEVE_PATH)


def test_search_sends_both_credentials(wired):
    transport = wired()
    with auth.bind(pm.hosted_headers()):
        retrieve.search("年假", knowledge_base_ids=[12])
    request = _retrieve_request(transport)
    assert request.method == "POST"
    assert str(request.url) == f"{pm.PLATFORM_BASE}{pm.RETRIEVE_PATH}"
    # 应用凭据证明「哪个应用」，访问者凭据证明「为谁」——两把都要，且不可对调。
    assert request.headers["Authorization"] == f"Bearer {pm.FAKE_APP_TOKEN}"
    assert request.headers["X-BiSheng-Access-Token"] == pm.FAKE_OBO


def test_body_is_field_for_field_and_none_ids_are_omitted(wired):
    transport = wired()
    with auth.bind(pm.hosted_headers()):
        retrieve.search("年假", knowledge_base_ids=[12, 13], top_k=3, max_content=999)
    body = _json(_retrieve_request(transport))
    assert body == {"query": "年假", "top_k": 3, "max_content": 999, "knowledge_base_ids": [12, 13]}

    transport = wired()
    with auth.bind(pm.hosted_headers()):
        retrieve.search("年假")
    # 服务端 schema 是 extra="forbid"；送 `null` 会 422，所以不指定就省略该键。
    assert "knowledge_base_ids" not in _json(_retrieve_request(transport))


def test_filters_use_the_servers_own_shape(wired):
    transport = wired()
    with auth.bind(pm.hosted_headers()):
        retrieve.search(
            "年假",
            knowledge_base_ids=[12],
            filters=[retrieve.KnowledgeBaseFilter(knowledge_base_id=12, tags=["hr"])],
        )
    body = _json(_retrieve_request(transport))
    assert body["filters"] == {
        "knowledge_base_filters": [{"knowledge_base_id": 12, "tags": ["hr"], "tag_match_mode": "ANY"}]
    }


def test_result_mirrors_the_facade_response(wired):
    wired()
    with auth.bind(pm.hosted_headers()):
        result = retrieve.search("年假", knowledge_base_ids=[12])
    assert result.total == 1
    chunk = result.chunks[0]
    assert chunk.content == "年假 5 天"
    assert (chunk.knowledge_id, chunk.document_id, chunk.chunk_index) == (12, 7, 3)
    assert chunk.document_name == "员工手册.pdf"
    assert chunk.document_update_time == "2026-09-01 10:00:00"


def test_no_visitor_credential_sends_nothing(mock_transport, platform_env, app_token_env):
    transport = mock_transport(pm.routes({}))
    with auth.bind(pm.hosted_headers(token=None)):
        with pytest.raises(VisitorCredentialMissingError):
            retrieve.search("年假", knowledge_base_ids=[12])
    with pytest.raises(VisitorCredentialMissingError):
        retrieve.search("年假", knowledge_base_ids=[12])
    assert transport.requests == []


def test_app_token_alone_is_never_enough(mock_transport, platform_env, app_token_env):
    """进程级环境里有应用凭据，但没有访问者——仍然拒绝，且一个请求都不发。"""
    transport = mock_transport(pm.routes({}))
    with pytest.raises(VisitorCredentialMissingError):
        retrieve.search("年假", knowledge_base_ids=[12])
    assert transport.requests == []


def test_visitor_credential_alone_is_refused_locally(mock_transport, platform_env):
    """应用凭据未注入（本地 `bisheng dev` 期就是这样）→ 明确、可区分的错误。"""
    transport = mock_transport(pm.routes({}))
    with auth.bind(pm.dev_headers()):
        with pytest.raises(AppCredentialMissingError):
            retrieve.search("年假", knowledge_base_ids=[12])
    assert transport.requests == []


def test_no_as_user_parameter():
    signature = inspect.signature(retrieve.search)
    assert {"as_user", "user_id", "on_behalf_of", "subject"}.isdisjoint(signature.parameters)
    assert inspect.signature(retrieve.asearch).parameters.keys() == signature.parameters.keys()


@pytest.mark.parametrize(
    ("http_status", "code", "data", "expected"),
    [
        (401, 26001, {}, VisitorCredentialRejectedError),
        (403, 26320, {}, VisitorCredentialRejectedError),
        (403, 26003, {"required": "knowledge:read"}, ScopeMissingError),
        (404, 26321, {"unreachable_ids": [9]}, TargetUnreachableError),
        (409, 26322, {"knowledge_id": 12}, CapabilityRevokedError),
        (400, 16273, {"capability": "财务档案", "reason": "revoked"}, CapabilityRevokedError),
        (400, 16274, {"capability": "knowledge"}, CapabilityNotDeclaredError),
        (503, 26030, {}, PermissionEvaluationError),
        (422, None, None, PlatformRefusedError),
    ],
)
def test_each_failure_kind_is_distinguishable(wired, http_status, code, data, expected):
    body = pm.v2_error_body(code, "拒绝", data) if code else {"detail": "validation error"}
    wired(pm.json_response(http_status, body))
    with auth.bind(pm.hosted_headers()):
        with pytest.raises(expected):
            retrieve.search("年假", knowledge_base_ids=[12])


def test_permission_outage_is_an_exception_not_an_empty_result(wired):
    wired(pm.json_response(503, pm.v2_error_body(26030, "鉴权依赖不可用")))
    with auth.bind(pm.hosted_headers()):
        with pytest.raises(PermissionEvaluationError):
            retrieve.search("年假", knowledge_base_ids=[12])


def test_incompatibility_surfaces_before_any_retrieval(mock_transport, platform_env, app_token_env):
    transport = mock_transport(
        pm.routes(
            {
                pm.VERSIONS_PATH: pm.json_response(
                    200, {"status_code": 200, "status_message": "", "data": pm.versions_payload(version=None)}
                )
            }
        )
    )
    with auth.bind(pm.hosted_headers()):
        with pytest.raises(PlatformTooOldError):
            retrieve.search("年假", knowledge_base_ids=[12])
    assert all(request.url.path != pm.RETRIEVE_PATH for request in transport.requests)


def test_two_visitors_get_their_own_results_and_nothing_is_cached(mock_transport, platform_env, app_token_env):
    def respond(request: httpx.Request) -> httpx.Response:
        visitor = request.headers["X-BiSheng-Access-Token"]
        content = "甲的结果" if visitor.endswith("1") else "乙的结果"
        return httpx.Response(
            200,
            json={
                "status_code": 200,
                "status_message": "",
                "data": pm.retrieve_payload([_chunk_with(content)]),
            },
        )

    transport = mock_transport(
        pm.routes(
            {
                pm.VERSIONS_PATH: pm.json_response(
                    200, {"status_code": 200, "status_message": "", "data": pm.versions_payload()}
                ),
                pm.RETRIEVE_PATH: respond,
            }
        )
    )

    with auth.bind(pm.hosted_headers(user_id="1", token="tok-1")):
        first = retrieve.search("同一个问题", knowledge_base_ids=[12])
    with auth.bind(pm.hosted_headers(user_id="2", token="tok-2")):
        second = retrieve.search("同一个问题", knowledge_base_ids=[12])

    assert first.chunks[0].content == "甲的结果"
    assert second.chunks[0].content == "乙的结果"
    assert len([r for r in transport.requests if r.url.path == pm.RETRIEVE_PATH]) == 2


async def test_async_twin_has_the_same_wire_shape(wired):
    transport = wired()
    with auth.bind(pm.hosted_headers()):
        result = await retrieve.asearch("年假", knowledge_base_ids=[12])
    request = _retrieve_request(transport)
    assert result.total == 1
    assert request.headers["Authorization"] == f"Bearer {pm.FAKE_APP_TOKEN}"
    assert request.headers["X-BiSheng-Access-Token"] == pm.FAKE_OBO


async def test_async_twin_refuses_without_a_visitor(mock_transport, platform_env, app_token_env):
    transport = mock_transport(pm.routes({}))
    with pytest.raises(VisitorCredentialMissingError):
        await retrieve.asearch("年假", knowledge_base_ids=[12])
    assert transport.requests == []


def _chunk_with(content: str) -> dict:
    row = pm.retrieve_payload()["chunks"][0].copy()
    row["content"] = content
    return row


def _json(request: httpx.Request) -> dict:
    import json

    return json.loads(request.content.decode("utf-8"))
