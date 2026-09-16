"""F051 T012 (errors half): what the face refuses, and in what shape."""

from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from test.open_api.model_gateway_fixtures import (
    FakeBishengLLM,
    build_model_face_app,
    capture_records,
    install_catalog,
    install_fake_llm,
    model_row,
    server_row,
    service_account_principal,
)

CHAT_PATH = "/api/v2/model/v1/chat/completions"
BODY = {"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]}


@pytest.fixture
def admitted(monkeypatch):
    monkeypatch.setattr(
        "bisheng.open_api.api.dependencies.validate_bearer",
        AsyncMock(return_value=service_account_principal()),
    )
    install_catalog(monkeypatch, [server_row(1, "azure-openai")], [model_row(10, 1, "gpt-4o")])
    install_fake_llm(monkeypatch, FakeBishengLLM())
    return capture_records(monkeypatch)


async def _call(method: str, path: str, **kwargs):
    app = build_model_face_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


async def test_an_empty_message_list_is_a_readable_400(admitted):
    response = await _call("POST", CHAT_PATH, json={"model": "gpt-4o", "messages": []})

    assert response.status_code == 400
    body = response.json()["error"]
    assert body["bisheng_code"] == 26203
    assert body["type"] == "invalid_request_error"
    assert body["param"] == "messages"


async def test_more_than_one_candidate_is_refused_rather_than_quietly_under_delivered(admitted):
    response = await _call("POST", CHAT_PATH, json={**BODY, "n": 2})

    assert response.status_code == 400
    assert response.json()["error"]["param"] == "n"


async def test_a_refused_header_is_reported_before_a_bad_body(admitted):
    response = await _call("POST", CHAT_PATH, json={**BODY, "n": 2}, headers={"X-End-User": "external-1"})

    # Two things are wrong; the caller hears about the header. Answering the
    # body first would give an agent a different verdict on each retry.
    assert response.json()["error"]["bisheng_code"] == 26205


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/v2/model/v1/embeddings"),
        ("POST", "/api/v2/model/v1/completions"),
        ("POST", "/api/v2/model/v1/responses"),
        ("POST", "/api/v2/model/v1/images/generations"),
        ("POST", "/api/v2/model/v1/audio/speech"),
        ("GET", "/api/v2/model/v1/files"),
        ("DELETE", "/api/v2/model/v1/assistants/a1"),
    ],
)
async def test_the_rest_of_the_openai_family_is_refused_readably(admitted, method, path):
    response = await _call(method, path, json={} if method == "POST" else None)

    assert response.status_code == 404
    body = response.json()["error"]
    assert body["bisheng_code"] == 26201
    assert body["code"] == "endpoint_not_supported"


async def test_the_anthropic_messages_path_gets_its_own_answer(admitted):
    response = await _call("POST", "/api/v2/model/v1/messages", json={})

    assert response.status_code == 404
    body = response.json()["error"]
    assert body["bisheng_code"] == 26202
    assert body["code"] == "anthropic_protocol_not_supported"


async def test_credentials_are_judged_before_the_path_is(monkeypatch):
    from bisheng.common.errcode.open_api import OpenApiCredentialMissingError

    monkeypatch.setattr(
        "bisheng.open_api.api.dependencies.validate_bearer",
        AsyncMock(side_effect=OpenApiCredentialMissingError()),
    )

    response = await _call("POST", "/api/v2/model/v1/embeddings", json={})

    # Otherwise an unauthenticated caller could enumerate which endpoints exist.
    assert response.status_code == 401
    assert response.json()["error"]["bisheng_code"] == 26001


async def test_an_unresolvable_model_is_a_404_with_the_reason(admitted):
    response = await _call("POST", CHAT_PATH, json={**BODY, "model": "never-configured"})

    assert response.status_code == 404
    body = response.json()["error"]
    assert body["bisheng_code"] == 26211
    assert body["code"] == "model_not_found"


async def test_an_ambiguous_bare_name_lists_the_qualified_alternatives(monkeypatch, admitted):
    install_catalog(
        monkeypatch,
        [server_row(1, "azure-openai"), server_row(2, "qwen-cloud")],
        [model_row(10, 1, "shared"), model_row(11, 2, "shared")],
    )

    response = await _call("POST", CHAT_PATH, json={**BODY, "model": "shared"})

    assert response.status_code == 400
    body = response.json()["error"]
    assert body["bisheng_code"] == 26214
    assert body["candidates"] == ["azure-openai/shared", "qwen-cloud/shared"]


async def test_an_undecidable_catalog_refuses_with_503_rather_than_a_narrower_set(monkeypatch, admitted):
    install_catalog(monkeypatch, [], [], fail_with=RuntimeError("openfga unreachable"))

    response = await _call("POST", CHAT_PATH, json=BODY)

    assert response.status_code == 503
    assert response.json()["error"]["bisheng_code"] == 26216


async def test_a_permission_backend_outage_is_still_openai_shaped(monkeypatch, admitted):
    from bisheng.common.errcode.permission import PermissionServiceUnavailableError

    async def explode(*_args, **_kwargs):
        raise PermissionServiceUnavailableError()

    monkeypatch.setattr(
        "bisheng.open_api.domain.services.model_gateway_service.list_callable_chat_models",
        explode,
    )

    response = await _call("GET", "/api/v2/model/v1/models")

    # That error has its own registered handler, which bypasses the shared
    # dispatch — without a branch there it would come back as the envelope.
    assert response.status_code == 503
    assert response.json()["error"]["type"] == "server_error"


async def test_neighbouring_v2_paths_keep_the_platform_envelope(monkeypatch):
    from bisheng.common.errcode.open_api import OpenApiCredentialMissingError
    from bisheng.main import app

    monkeypatch.setattr(
        "bisheng.open_api.api.dependencies.validate_bearer",
        AsyncMock(side_effect=OpenApiCredentialMissingError()),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v2/auth/whoami")

    assert response.status_code == 401
    assert response.json()["status_code"] == 26001
    assert "error" not in response.json()
