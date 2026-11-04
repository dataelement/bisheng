"""T041 覆盖 AC-01, AC-02, AC-04, AC-13, AC-14。"""

import hashlib
import hmac
import json
from datetime import UTC
from importlib import import_module

import httpx
import pytest
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.sso_sync import KunlianDependencyUnavailableError
from bisheng.common.errcode.user import UserNoWebMenuForLoginError
from test.sso import test_kunlian_login_contract as login_tests

owner = login_tests.owner
directory_store = login_tests.directory_store
projection = login_tests.projection
login = login_tests.login
PATH = login_tests.PATH


@pytest.fixture
async def internal_api(login):
    module = import_module("bisheng.sso_sync.api.endpoints.kunlian")
    from bisheng.sso_sync.api.router import router
    from bisheng.sso_sync.application.kunlian import KunlianApiBindings, KunlianLoginApplication

    service = login[1]
    cfg = service.config.model_copy(update={"trusted_gateway_networks": ["192.0.2.0/24"]})
    bindings = KunlianApiBindings(config=cfg, login=KunlianLoginApplication(service))
    app = FastAPI()

    @app.exception_handler(BaseErrorCode)
    async def legacy_handler(request, error):
        return JSONResponse(status_code=200, content={"legacy": True})

    api = APIRouter(prefix="/api/v1")
    api.include_router(router)
    app.include_router(api)
    app.dependency_overrides[module.get_api_bindings] = lambda: bindings
    now = int(service.clock().replace(tzinfo=UTC).timestamp())
    counter = 0

    def signed(raw):
        nonlocal counter
        counter += 1
        nonce = f"fixture-http-{counter:025d}"
        message = "\n".join(
            ("v1", "POST", PATH, "fixture-key", str(now), nonce, hashlib.sha256(raw).hexdigest())
        ).encode()
        return {
            "Content-Type": "application/json",
            "X-Kunlian-Key-Id": "fixture-key",
            "X-Kunlian-Timestamp": str(now),
            "X-Kunlian-Nonce": nonce,
            "X-Kunlian-Signature": hmac.new(login_tests.SECRET.encode(), message, hashlib.sha256).hexdigest(),
        }

    async def send(*, body=None, headers=None, peer="192.0.2.10", path=PATH, raw=None):
        content = raw if raw is not None else json.dumps(login[9] if body is None else body, indent=2).encode()
        request_headers = signed(content)
        request_headers.update(headers or {})
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=(peer, 4444)), base_url="http://test"
        ) as client:
            return await client.post(path, content=content, headers=request_headers)

    return send, signed, app, bindings


async def test_raw_body_and_idempotent_local_result(internal_api, login):
    send, _, _, _ = internal_api
    first = await send()
    second = await send()
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert set(first.json()["data"]) == {"local_jwt", "expires_at", "user_id", "tenant_id"}
    assert first.json()["data"]["user_id"] == login[10]
    assert not any(
        secret in first.text for secret in ("fixture-private-AT", "fixture-private-IDT", "expected_nonce", "summary")
    )


@pytest.mark.parametrize(
    "case", ["peer", "cookie", "bearer", "origin", "forwarded", "query", "encoded_path", "signature", "oversize"]
)
async def test_untrusted_requests_never_reach_idp(internal_api, login, case):
    send, _, _, _ = internal_api
    kwargs = {
        "peer": {"peer": "198.51.100.1"},
        "cookie": {"headers": {"Cookie": "access_token=forged"}},
        "bearer": {"headers": {"Authorization": "Bearer forged"}},
        "origin": {"headers": {"Origin": "https://fixture.example"}},
        "forwarded": {"headers": {"X-Forwarded-For": "192.0.2.10"}, "peer": "198.51.100.1"},
        "query": {"path": PATH + "?user_id=1"},
        "encoded_path": {"path": PATH.replace("login", "%6cogin")},
        "signature": {"headers": {"X-Kunlian-Signature": "0" * 64}},
        "oversize": {"raw": b" " * 65537},
    }[case]
    response = await send(**kwargs)
    assert response.status_code == 403
    assert response.json()["data"]["reason_code"] == "TRUST_REJECTED"
    login[4].verify_id_token.assert_not_awaited()


async def test_unknown_fields_and_real_failure_http_status(internal_api, login):
    send, _, _, _ = internal_api
    response = await send(body={**login[9], "user_id": 1})
    assert response.status_code == 400 and response.json()["data"]["reason_code"] == "LOGIN_INVALID"
    login[3].require_login_access.side_effect = UserNoWebMenuForLoginError()
    response = await send()
    assert response.status_code == 403 and response.json()["status_code"] == 10611
    login[3].require_login_access.side_effect = KunlianDependencyUnavailableError(exception=ValueError("private-value"))
    response = await send()
    assert response.status_code == 503 and "private-value" not in response.text


async def test_replay_default_source_deny_and_unassembled_runtime(internal_api):
    _, signed, app, bindings = internal_api
    content = b"{}"
    headers = signed(content)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("192.0.2.10", 4444)), base_url="http://test"
    ) as client:
        first = await client.post(PATH, content=content, headers=headers)
        assert first.status_code == 400
        replay = await client.post(PATH, content=content, headers=headers)
        assert replay.status_code == 403
        bindings.config.trusted_gateway_networks = []
        denied = await client.post(PATH, content=content, headers=signed(content))
        assert denied.status_code == 403
        app.dependency_overrides.clear()
        unavailable = await client.post(PATH, content=content, headers=signed(content))
        assert unavailable.status_code == 403


@pytest.mark.parametrize("status", [401, 403])
async def test_authentication_dependency_preserves_real_http(internal_api, status):
    _, _, app, _ = internal_api

    async def refused():
        raise HTTPException(status_code=status, detail="private-authentication-details")

    app.dependency_overrides[UserPayload.get_login_user] = refused
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/identity-integrations/kunlian/status")
        assert response.status_code == status and "private-authentication-details" not in response.text


async def test_missing_cookie_keeps_real_unauthenticated_http_and_does_not_select_kunlian_login(internal_api):
    from bisheng.common.exceptions.auth import AuthJWTException
    from bisheng.user.domain.services.auth import AuthJwt
    from test.sso.test_kunlian_http_admission import auth

    _, _, app, _ = internal_api

    def fixture_auth(request: Request):
        return auth(request)

    @app.exception_handler(AuthJWTException)
    async def legacy_auth_error(request, error):
        return JSONResponse(status_code=401, content={"detail": str(error)})

    app.dependency_overrides[AuthJwt] = fixture_auth
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/identity-integrations/kunlian/status")
        assert response.status_code == 401 and response.json()["data"] is None
        assert "reason_code" not in response.text


async def test_internal_redemption_is_server_only_bound_and_single_use_even_when_login_is_disabled(internal_api, login):
    from dataclasses import replace

    from bisheng.sso_sync.application.kunlian import KunlianLogoutApplication
    from bisheng.sso_sync.domain.services.kunlian_logout import KunlianLogoutService

    _, _, app, bindings = internal_api
    module = import_module("bisheng.sso_sync.api.endpoints.kunlian")
    result = await login[0]()
    repository, service = login[2], login[1]
    await repository.revoke_session(result.session_reference, "LOGOUT")
    ticket = await repository.issue_logout_ticket(result.session_reference, "b" * 64)
    bindings.config.login_enabled = False
    protocol = KunlianLogoutApplication(
        KunlianLogoutService(repository, bindings.config, sessions=None, trust=service.trust)
    )
    app.dependency_overrides[module.get_api_bindings] = lambda: replace(bindings, protocol=protocol)
    path = "/api/v1/internal/kunlian/logout-ticket:redeem"
    counter = 0

    def signed(raw):
        nonlocal counter
        counter += 1
        now = int(service.clock().replace(tzinfo=UTC).timestamp())
        nonce = f"fixture-redeem-{counter:025d}"
        message = "\n".join(
            ("v1", "POST", path, "fixture-key", str(now), nonce, hashlib.sha256(raw).hexdigest())
        ).encode()
        return {
            "Content-Type": "application/json",
            "X-Kunlian-Key-Id": "fixture-key",
            "X-Kunlian-Timestamp": str(now),
            "X-Kunlian-Nonce": nonce,
            "X-Kunlian-Signature": hmac.new(login_tests.SECRET.encode(), message, hashlib.sha256).hexdigest(),
        }

    body = {"connection_id": "fixture", "ticket": ticket.get_secret_value(), "browser_binding_hash": "b" * 64}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("192.0.2.10", 4444)), base_url="http://test"
    ) as client:
        raw = json.dumps(body).encode()
        forbidden = await client.post(path, content=raw, headers={**signed(raw), "Cookie": "fixture=browser"})
        assert forbidden.status_code == 403
        wrong = json.dumps({**body, "browser_binding_hash": "c" * 64}).encode()
        assert (await client.post(path, content=wrong, headers=signed(wrong))).status_code == 403
        success = await client.post(path, content=raw, headers=signed(raw))
        assert success.status_code == 200 and success.headers["cache-control"] == "no-store"
        assert success.json()["data"] == {
            "id_token_hint": "fixture-private-IDT",
            "client_id": "fixture-client",
            "local_session_revoked": True,
        }
        assert (await client.post(path, content=raw, headers=signed(raw))).status_code == 403
