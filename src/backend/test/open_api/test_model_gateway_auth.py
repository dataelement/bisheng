"""F051 T012 (auth half): credential admission on the model protocol face.

None of this is new authentication code — the face inherits the one ``/api/v2``
credential dependency. What is asserted here is that the inherited verdicts
arrive in the OpenAI error shape, which is the only thing an official client can
read, and that the one gap in the shared base (a well-formed ``X-End-User``
being adopted in silence) is closed by this face rather than left open.
"""

from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from bisheng.common.errcode.open_api import (
    OpenApiCredentialInvalidError,
    OpenApiCredentialMissingError,
    OpenApiDelegateLocalDevRefusedError,
    OpenApiScopeMissingError,
)
from test.open_api.model_gateway_fixtures import (
    FakeBishengLLM,
    build_model_face_app,
    capture_records,
    install_fake_llm,
    service_account_principal,
)

CHAT_PATH = "/api/v2/model/v1/chat/completions"
MODELS_PATH = "/api/v2/model/v1/models"
BODY = {"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]}


def _admit(monkeypatch, principal_or_error):
    if isinstance(principal_or_error, Exception):
        mock = AsyncMock(side_effect=principal_or_error)
    else:
        mock = AsyncMock(return_value=principal_or_error)
    monkeypatch.setattr("bisheng.open_api.api.dependencies.validate_bearer", mock)


async def _call(app, method: str, path: str, **kwargs):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (OpenApiCredentialMissingError(), 26001),
        (OpenApiCredentialInvalidError(), 26002),
    ],
)
async def test_credential_failures_are_openai_shaped_401s(monkeypatch, error, code):
    _admit(monkeypatch, error)

    response = await _call(build_model_face_app(), "POST", CHAT_PATH, json=BODY)

    assert response.status_code == 401
    body = response.json()["error"]
    assert body["type"] == "authentication_error"
    assert body["code"] == "invalid_api_key"
    assert body["bisheng_code"] == code


@pytest.mark.parametrize("path,method", [(CHAT_PATH, "POST"), (MODELS_PATH, "GET")])
async def test_a_key_without_model_invoke_is_refused_on_both_promised_endpoints(monkeypatch, path, method):
    _admit(monkeypatch, service_account_principal(scopes=frozenset({"chat:invoke"})))

    response = await _call(build_model_face_app(), method, path, json=BODY if method == "POST" else None)

    assert response.status_code == 403
    body = response.json()["error"]
    assert body["bisheng_code"] == 26003
    assert body["code"] == "insufficient_scope"
    # The agent has to learn *which* scope to ask an administrator for.
    assert "model:invoke" in body["message"]


async def test_scope_edits_take_effect_on_the_next_call_without_reissuing(monkeypatch):
    app = build_model_face_app()
    records = capture_records(monkeypatch)
    install_fake_llm(monkeypatch, FakeBishengLLM())

    _admit(monkeypatch, service_account_principal(scopes=frozenset({"chat:invoke"})))
    refused = await _call(app, "GET", MODELS_PATH)

    _admit(monkeypatch, service_account_principal(scopes=frozenset({"chat:invoke", "model:invoke"})))
    monkeypatch.setattr(
        "bisheng.open_api.domain.services.model_gateway_service.list_callable_chat_models",
        AsyncMock(return_value=[]),
    )
    allowed = await _call(app, "GET", MODELS_PATH)

    assert refused.status_code == 403
    assert allowed.status_code == 200
    # Listing models is not a model call and never produces a usage row.
    assert records == []


async def test_delegation_only_key_is_refused_by_scope_not_by_a_parameter_error(monkeypatch):
    _admit(monkeypatch, OpenApiDelegateLocalDevRefusedError())

    for path, method in ((CHAT_PATH, "POST"), (MODELS_PATH, "GET"), ("/api/v2/model/v1/embeddings", "POST")):
        response = await _call(build_model_face_app(), method, path, json=BODY if method == "POST" else None)
        assert response.status_code == 403
        body = response.json()["error"]
        assert body["bisheng_code"] == 26051
        assert body["code"] == "delegate_only_credential"


async def test_an_unregistered_scope_error_still_renders_openai_shaped(monkeypatch):
    _admit(monkeypatch, OpenApiScopeMissingError(required="model:invoke"))

    response = await _call(build_model_face_app(), "GET", MODELS_PATH)

    assert response.status_code == 403
    assert response.json()["error"]["bisheng_code"] == 26003


@pytest.mark.parametrize(
    ("headers", "code"),
    [
        ({"X-On-Behalf-Of": "9"}, 26004),
        ({"X-End-User": "external-1"}, 26205),
        ({"X-On-Behalf-Of": "9", "X-End-User": "external-1"}, 26010),
        ({"x-foo-on-behalf-of": "9"}, 26019),
    ],
)
async def test_identity_headers_are_refused_and_never_reach_the_model(monkeypatch, headers, code):
    _admit(monkeypatch, service_account_principal())
    records = capture_records(monkeypatch)
    fake = install_fake_llm(monkeypatch, FakeBishengLLM())

    response = await _call(build_model_face_app(), "POST", CHAT_PATH, json=BODY, headers=headers)

    assert response.status_code in (400, 403)
    assert response.json()["error"]["bisheng_code"] == code
    assert fake.seen_messages == []
    assert records == []


async def test_a_user_id_in_the_body_is_refused(monkeypatch):
    _admit(monkeypatch, service_account_principal())

    response = await _call(build_model_face_app(), "POST", CHAT_PATH, json={**BODY, "user_id": 9})

    assert response.json()["error"]["bisheng_code"] == 26019


async def test_an_access_token_on_a_service_account_key_is_refused(monkeypatch):
    _admit(monkeypatch, service_account_principal())
    records = capture_records(monkeypatch)
    fake = install_fake_llm(monkeypatch, FakeBishengLLM())

    response = await _call(
        build_model_face_app(),
        "POST",
        CHAT_PATH,
        json=BODY,
        headers={"X-BiSheng-Access-Token": "whatever"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["bisheng_code"] == 26204
    assert fake.seen_messages == []
    assert records == []
