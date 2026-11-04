"""T045 覆盖 AC-07, AC-08, AC-13, AC-14, AC-17, AC-25, AC-26。"""

import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import jwt
import pytest
from fastapi import Depends, FastAPI, Request

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.sso_sync import KunlianDependencyUnavailableError, KunlianSessionExpiredError
from bisheng.user.domain.services.auth import AuthJwt
from test.sso import test_kunlian_login_contract as login_tests

owner = login_tests.owner
directory_store = login_tests.directory_store
projection = login_tests.projection
login = login_tests.login
SECRET = "fixture-http-HS256-secret-at-least-32-characters"
COOKIE = "access_token_cookie"


def auth(request=None):
    signer = AuthJwt.__new__(AuthJwt)
    signer.req = request
    signer.jwt_secret = SECRET
    signer.cookie_conf = SimpleNamespace(jwt_iss="fixture-local", jwt_token_expire_time=3600)
    signer._access_cookie_key = COOKIE
    signer._encode_algorithm, signer._decode_algorithms = "HS256", ["HS256"]
    return signer


def token(subject):
    return jwt.encode(
        {"sub": json.dumps(subject), "iss": "fixture-local", "exp": int(time.time()) + 300}, SECRET, algorithm="HS256"
    )


@pytest.fixture
async def browser_api(login, monkeypatch):
    from pydantic import SecretStr

    from bisheng.sso_sync.application.browser import KunlianBrowserApplication
    from bisheng.sso_sync.application.kunlian import KunlianSessionApplication
    from bisheng.sso_sync.domain.services.kunlian_session import KunlianSessionService
    from bisheng.utils import http_middleware as middleware

    call, service, repository, user_owner, idp, _, _, _, signed, _, _, _ = login
    await call()
    user_owner.global_super_checker = AsyncMock(return_value=False)
    session_service = KunlianSessionService(
        repository,
        service.config,
        idp_client=idp,
        user_owner=user_owner,
        tenant_owner=service.tenant_owner,
        multi_tenant_enabled=True,
        csrf_secret=SecretStr("fixture-csrf-secret"),
    )
    browser = KunlianBrowserApplication(
        config=service.config,
        repository=repository,
        user_owner=user_owner,
        sessions=KunlianSessionApplication(session_service),
    )
    app = FastAPI()
    app.state.kunlian_browser_application = browser
    app.add_middleware(middleware.CustomMiddleware)

    def initialize_auth(self, req=None, res=None):
        self.__dict__.update(auth(req).__dict__)

    monkeypatch.setattr(AuthJwt, "__init__", initialize_auth)
    monkeypatch.setattr(middleware, "_decode_jwt_subject", lambda value: auth().decode_jwt_token(value))
    monkeypatch.setattr(middleware, "_apply_token_version_and_visible", AsyncMock(return_value=None))
    monkeypatch.setattr(middleware, "_set_tenant_context", lambda *args, **kwargs: 7)

    def request_auth(request: Request):
        return auth(request)

    app.dependency_overrides[AuthJwt] = request_auth

    @app.api_route("/api/v1/probe", methods=["GET", "POST"])
    async def probe(request: Request, user=Depends(UserPayload.get_login_user)):
        second = await UserPayload.get_login_user(auth(request))
        assert second is user
        return {"user_id": user.user_id, "tenant_id": user.tenant_id}

    subject = signed[0][0]
    idp.introspect.reset_mock()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://fixture.example") as client:
        yield client, browser, token(subject), subject, idp, repository, session_service


async def test_one_introspection_per_http_request_including_identity_dependency(browser_api):
    client, _, cookie, _, idp, _, _ = browser_api
    for _ in range(2):
        response = await client.get("/api/v1/probe", headers={"Cookie": f"{COOKIE}={cookie}"})
        assert response.status_code == 200 and response.json()["tenant_id"] == 7
    assert idp.introspect.await_count == 2


async def test_subject_mismatch_persistently_revokes_session_before_rejecting(browser_api):
    """AC-17, AC-26:签名主体错配后必须落库撤销。原正确 Cookie 也不能复活。"""
    client, _, original, subject, _, repository, _ = browser_api
    changed = {**subject, "tenant_id": subject["tenant_id"] + 1}
    response = await client.get("/api/v1/probe", headers={"Cookie": f"{COOKIE}={token(changed)}"})
    assert response.status_code == 401
    assert response.json()["data"]["reason_code"] == "SESSION_EXPIRED"
    with pytest.raises(KunlianSessionExpiredError):
        await repository.load_admission_facts(subject["kunlian_session"])
    assert (await client.get("/api/v1/probe", headers={"Cookie": f"{COOKIE}={original}"})).status_code == 401


@pytest.mark.parametrize(
    "case",
    [
        "bearer",
        "duplicate_cookie",
        "missing_ref",
        "missing_source",
        "stripped_markers",
        "identity_header",
        "bad_origin",
        "missing_csrf",
    ],
)
async def test_cookie_only_ambiguity_stripped_markers_and_write_trust(browser_api, case):
    client, _, cookie, subject, idp, _, _ = browser_api
    headers = {"Cookie": f"{COOKIE}={cookie}"}
    method = "GET"
    if case == "bearer":
        headers = {"Authorization": "Bearer " + cookie}
    elif case == "duplicate_cookie":
        headers["Cookie"] += f"; {COOKIE}={cookie}"
    elif case in {"missing_ref", "missing_source", "stripped_markers"}:
        keys = (
            {"kunlian_session"}
            if case == "missing_ref"
            else {"auth_source"}
            if case == "missing_source"
            else {"auth_source", "kunlian_session"}
        )
        headers["Cookie"] = f"{COOKIE}=" + token({key: value for key, value in subject.items() if key not in keys})
    elif case == "identity_header":
        headers["X-User-Id"] = "1"
    elif case == "bad_origin":
        headers["Origin"] = "https://other.example"
    else:
        method = "POST"
        headers["Origin"] = "https://fixture.example"
    response = await client.request(method, "/api/v1/probe", headers=headers)
    assert response.status_code == 403 and response.json()["data"]["reason_code"] == "TRUST_REJECTED"
    idp.introspect.assert_not_awaited()


async def test_write_csrf_and_dependency_vs_expired_http(browser_api):
    client, browser, cookie, subject, idp, _, _ = browser_api
    csrf = await browser.sessions.derive_csrf(subject["kunlian_session"])
    headers = {"Cookie": f"{COOKIE}={cookie}", "Origin": "https://fixture.example", "X-CSRF-Token": csrf}
    assert (await client.post("/api/v1/probe", headers=headers)).status_code == 200
    idp.introspect.side_effect = KunlianDependencyUnavailableError()
    assert (await client.get("/api/v1/probe", headers=headers)).status_code == 503
    idp.introspect.side_effect = KunlianSessionExpiredError()
    assert (await client.get("/api/v1/probe", headers=headers)).status_code == 401


async def test_other_credential_channels_do_not_introspect_browser_cookie(browser_api):
    client, _, cookie, _, idp, _, _ = browser_api
    response = await client.get("/api/v2/not-a-browser-route", headers={"Cookie": f"{COOKIE}={cookie}"})
    assert response.status_code == 404
    idp.introspect.assert_not_awaited()


async def test_quoted_cookie_and_binding_only_identity_cannot_bypass(browser_api, login):
    from bisheng.user.domain.models.user import User

    client, _, cookie, subject, idp, _, _ = browser_api
    response = await client.get("/api/v1/probe", headers={"Cookie": f'{COOKIE}="{cookie}"'})
    assert response.status_code == 200
    idp.introspect.reset_mock()
    async with login[6]() as session:
        user = await session.get(User, subject["user_id"])
        user.source, user.external_id = "local", None
        session.add(user)
        await session.commit()
    stripped = token({key: value for key, value in subject.items() if key not in {"auth_source", "kunlian_session"}})
    response = await client.get("/api/v1/probe", headers={"Cookie": f'{COOKIE}="{stripped}"'})
    assert response.status_code == 403
    idp.introspect.assert_not_awaited()


async def test_classification_store_failure_refuses_and_local_identity_keeps_old_channel(
    browser_api, login, monkeypatch
):
    from bisheng.user.domain.models.user import User

    client, browser, _, _, idp, _, _ = browser_api
    async with login[6]() as session:
        local = User(user_name="原本地用户", source="local", password="")
        session.add(local)
        await session.commit()
    cookie = token({"user_id": local.user_id, "user_name": local.user_name, "tenant_id": 7, "token_version": 0})
    response = await client.get("/api/v1/ordinary-route-not-mounted", headers={"Cookie": f"{COOKIE}={cookie}"})
    assert response.status_code == 404
    idp.introspect.assert_not_awaited()
    monkeypatch.setattr(
        browser.user_owner, "is_reserved_external_account", AsyncMock(side_effect=OSError("private-store-error"))
    )
    response = await client.get("/api/v1/probe", headers={"Cookie": f"{COOKIE}={cookie}"})
    assert response.status_code == 503 and "private-store-error" not in response.text


async def test_expired_local_jwt_returns_session_expired(browser_api):
    client, _, _, subject, idp, _, _ = browser_api
    expired = jwt.encode(
        {"sub": json.dumps(subject), "iss": "fixture-local", "exp": int(time.time()) - 1}, SECRET, algorithm="HS256"
    )
    response = await client.get("/api/v1/probe", headers={"Cookie": f"{COOKIE}={expired}"})
    assert response.status_code == 401 and response.json()["data"]["reason_code"] == "SESSION_EXPIRED"
    idp.introspect.assert_not_awaited()


@pytest.mark.parametrize("shape", ["string", "float"])
async def test_legacy_numeric_user_id_shape_cannot_hide_reserved_source(browser_api, monkeypatch, shape):
    client, _, _, subject, idp, _, _ = browser_api
    legacy = SimpleNamespace(user_id=subject["user_id"], tenant_id=7, token_version=subject["token_version"])
    monkeypatch.setattr(UserPayload, "init_login_user", AsyncMock(return_value=legacy))
    stripped = {key: value for key, value in subject.items() if key not in {"auth_source", "kunlian_session"}}
    stripped["user_id"] = str(subject["user_id"]) if shape == "string" else float(subject["user_id"])
    response = await client.get("/api/v1/probe", headers={"Cookie": f"{COOKIE}=" + token(stripped)})
    assert response.status_code == 403 and response.json()["data"]["reason_code"] == "TRUST_REJECTED"
    UserPayload.init_login_user.assert_not_awaited()
    idp.introspect.assert_not_awaited()


async def test_binding_cookie_alone_is_anonymous_and_does_not_load_login_runtime(browser_api, monkeypatch):
    from bisheng.sso_sync.application import browser as module

    client, _, _, _, idp, _, _ = browser_api
    lookup = AsyncMock(side_effect=AssertionError("anonymous request must not load authentication runtime"))
    monkeypatch.setattr(module, "get_browser_application", lookup)
    response = await client.get(
        "/api/v1/ordinary-route-not-mounted", headers={"Cookie": "kunlian_browser_binding=fixture-binding-only"}
    )
    assert response.status_code == 404
    lookup.assert_not_awaited()
    idp.introspect.assert_not_awaited()


async def test_runtime_requires_explicit_secrets_and_reuses_only_network_client(monkeypatch):
    from cryptography.fernet import Fernet
    from pydantic import SecretStr

    from bisheng.common.services import config_service
    from bisheng.core.config.sso_sync import KunlianConf
    from bisheng.sso_sync.application.runtime import KunlianRuntimeProvider, resolve_environment_secret
    from test.sso.test_kunlian_admission import config

    settings = SimpleNamespace(
        sso_sync=SimpleNamespace(kunlian=KunlianConf()),
        multi_tenant=SimpleNamespace(enabled=True),
        aget_from_db=AsyncMock(return_value=False),
    )
    monkeypatch.setattr(config_service, "settings", settings)
    provider = KunlianRuntimeProvider()
    assert (await provider.api_bindings()).login is None
    assert (await provider.browser_application()).sessions is None
    settings.aget_from_db.assert_not_awaited()
    with pytest.raises(LookupError):
        resolve_environment_secret("not-an-env-reference")
    cfg = config()
    cfg.endpoint_allowlist = [
        cfg.issuer + path for path in ("/.well-known/openid-configuration", "/oidc/jwks", "/oidc/introspect")
    ]
    settings.sso_sync.kunlian = cfg
    values = {
        getattr(cfg, name): SecretStr("fixture-independent-" + name)
        for name in (
            "client_secret_reference",
            "sync_key_reference",
            "internal_secret_reference",
            "csrf_secret_reference",
        )
    }
    values[cfg.encryption_secret_reference] = SecretStr(Fernet.generate_key().decode())
    provider.secret_resolver = values.__getitem__
    first = await provider.api_bindings()
    idp = provider._idp
    try:
        second = await provider.api_bindings()
        assert first is second and provider._idp is idp and first.login.service.allow_multi_login is False
        encrypted = provider.directory_service.encrypt_cursor("fixture-cursor")
        assert provider.directory_service.decrypt_cursor(encrypted) == "fixture-cursor"
        assert encrypted != "fixture-cursor" and not provider.directory_service.readiness_probe()
        values[cfg.encryption_secret_reference] = SecretStr("invalid-key")
        assert (await provider.api_bindings()).login is None and provider._idp is None
        assert "ENCRYPTION_KEY_UNAVAILABLE" in provider.directory_service.readiness_probe()
    finally:
        await provider.aclose()
