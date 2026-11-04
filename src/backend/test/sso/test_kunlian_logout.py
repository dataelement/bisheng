"""T064 覆盖 AC-07, AC-10, AC-11, AC-13, AC-14, AC-21, AC-25, AC-26。"""

from hashlib import sha256
from importlib import import_module
from unittest.mock import AsyncMock

import pytest
from fastapi import Request, Response
from pydantic import SecretStr
from sqlalchemy.exc import OperationalError

from bisheng.common.errcode.sso_sync import KunlianTrustRejectedError
from bisheng.sso_sync.domain.models.kunlian import KunlianWebSession
from bisheng.user.domain.services.auth import AuthJwt
from test.sso import test_kunlian_http_admission as http_tests
from test.sso import test_kunlian_session_store as store_tests

owner = http_tests.owner
directory_store = http_tests.directory_store
projection = http_tests.projection
login = http_tests.login
browser_api = http_tests.browser_api
session_store = store_tests.session_store
BINDING = "b" * 43
CSRF = "/api/v1/identity-integrations/kunlian/session/csrf"
LOGOUT = "/api/v1/user/logout"


@pytest.fixture
async def logout_api(browser_api):
    from bisheng.sso_sync.application.kunlian import KunlianLogoutApplication
    from bisheng.sso_sync.domain.services.kunlian_logout import KunlianLogoutService

    client, browser, cookie, subject, idp, repository, sessions = browser_api
    async with repository.session_factory() as sql:
        from sqlmodel import select

        web = (await sql.exec(select(KunlianWebSession))).one()
        web.browser_binding_hash = sha256(BINDING.encode()).hexdigest()
        sql.add(web)
        await sql.commit()
    browser.protocol = KunlianLogoutApplication(KunlianLogoutService(repository, browser.config, sessions=sessions))
    app = client._transport.app
    app.include_router(import_module("bisheng.sso_sync.api.router").router, prefix="/api/v1")
    app.include_router(import_module("bisheng.user.api.user").router, prefix="/api/v1")

    def request_auth(request: Request, response: Response):
        signer = http_tests.auth(request)
        signer.res = response
        signer.cookie_conf.path, signer.cookie_conf.domain = "/", None
        return signer

    app.dependency_overrides[AuthJwt] = request_auth
    headers = {"Cookie": f"access_token_cookie={cookie}; kunlian_browser_binding={BINDING}"}
    return client, browser, subject, idp, repository, headers


async def test_expired_at_and_disabled_login_allow_only_protocol_then_persist_local_logout(logout_api):
    client, browser, _, idp, repository, headers = logout_api
    repository.clock.advance(301)
    browser.config.login_enabled = browser.config.directory_enabled = False
    csrf = await client.get(CSRF, headers=headers)
    assert csrf.status_code == 200 and csrf.headers["cache-control"] == "no-store"
    csrf_value = csrf.json()["data"]["csrf_token"]
    failed = await client.get("/api/v1/probe", headers=headers)
    assert failed.status_code != 200
    result = await client.post(
        LOGOUT, headers={**headers, "Origin": browser.config.public_origin, "X-CSRF-Token": csrf_value}
    )
    assert result.status_code == 200
    payload = result.json()["data"]
    assert payload["auth_source"] == "kunlian" and payload["local_logged_out"] is True
    assert payload["next_action"]["url"] == "/api/kunlian/logout" and payload["next_action"]["method"] == "POST"
    assert "access_token_cookie=" in result.headers["set-cookie"] and "Max-Age=0" in result.headers["set-cookie"]
    assert "kunlian_browser_binding" not in result.headers["set-cookie"]
    async with repository.session_factory() as sql:
        from sqlmodel import select

        assert (await sql.exec(select(KunlianWebSession))).one().state == "REVOKED"
    idp.introspect.assert_not_awaited()
    assert "fixture-private" not in result.text


@pytest.mark.parametrize(
    "case", ["origin", "csrf", "binding", "duplicate_binding", "subject", "wrong_path", "wrong_method"]
)
async def test_protocol_does_not_become_an_identity_or_bypass_browser_binding(logout_api, case):
    client, browser, subject, _, _, headers = logout_api
    response = await client.get(CSRF, headers=headers)
    assert response.status_code == 200
    write = {**headers, "Origin": browser.config.public_origin, "X-CSRF-Token": response.json()["data"]["csrf_token"]}
    method, path = "POST", LOGOUT
    if case == "origin":
        write["Origin"] = "https://attacker.invalid"
    elif case == "csrf":
        write["X-CSRF-Token"] = "0" * 64
    elif case == "binding":
        write["Cookie"] = write["Cookie"].replace(BINDING, "z" * 43)
    elif case == "duplicate_binding":
        write["Cookie"] += f"; kunlian_browser_binding={BINDING}"
    elif case == "subject":
        forged = http_tests.token({**subject, "user_id": subject["user_id"] + 1})
        write["Cookie"] = f"access_token_cookie={forged}; kunlian_browser_binding={BINDING}"
    elif case == "wrong_path":
        path = CSRF + "/extra"
    else:
        path, method = CSRF, "POST"
    result = await client.request(method, path, headers=write)
    assert result.status_code != 200
    assert "local_logged_out" not in result.text


async def test_sql_revocation_failure_keeps_cookie_and_retry_does_not_revive_session(logout_api, monkeypatch):
    client, browser, _, _, repository, headers = logout_api
    csrf = (await client.get(CSRF, headers=headers)).json()["data"]["csrf_token"]
    original = repository.revoke_session
    monkeypatch.setattr(
        repository,
        "revoke_session",
        AsyncMock(side_effect=OperationalError("private-SQL", None, RuntimeError("private-error"))),
    )
    write = {**headers, "Origin": browser.config.public_origin, "X-CSRF-Token": csrf}
    result = await client.post(LOGOUT, headers=write)
    assert result.status_code == 503 and "set-cookie" not in result.headers
    assert "private" not in result.text and "local_logged_out" not in result.text
    monkeypatch.setattr(repository, "revoke_session", original)
    first = await client.post(LOGOUT, headers=write)
    assert first.status_code == 200
    fresh = (await client.get(CSRF, headers=headers)).json()["data"]["csrf_token"]
    second = await client.post(LOGOUT, headers={**write, "X-CSRF-Token": fresh})
    assert second.status_code == 200
    assert (await client.get("/api/v1/probe", headers=headers)).status_code == 401


async def test_redemption_checks_registered_connection_and_client_before_consuming(session_store):
    repository, _, clock, bindings = session_store
    issued = await store_tests.issue(repository, clock, bindings[0])
    await repository.revoke_session(issued.reference, "LOGOUT")
    ticket = await repository.issue_logout_ticket(issued.reference, "b" * 64)
    for connection, client in (("other", "fixture-client"), ("fixture", "other")):
        with pytest.raises(KunlianTrustRejectedError):
            await repository.redeem_logout_ticket(
                ticket, "b" * 64, expected_connection_id=connection, expected_client_id=client
            )
    material = await repository.redeem_logout_ticket(
        ticket, "b" * 64, expected_connection_id="fixture", expected_client_id="fixture-client"
    )
    assert material.client_id == "fixture-client" and isinstance(material.id_token, SecretStr)
    with pytest.raises(KunlianTrustRejectedError):
        await repository.redeem_logout_ticket(
            ticket, "b" * 64, expected_connection_id="fixture", expected_client_id="fixture-client"
        )


async def test_ordinary_logout_retains_old_result_and_csrf_does_not_select_kunlian(logout_api, monkeypatch):
    from bisheng.admin.domain.services.tenant_scope import TenantScopeService

    client, _, _, idp, _, _ = logout_api
    monkeypatch.setattr(TenantScopeService, "clear_on_logout", AsyncMock())
    cookie = http_tests.token({"user_id": 9999, "user_name": "legacy", "tenant_id": 7, "token_version": 0})
    headers = {"Cookie": f"access_token_cookie={cookie}"}
    csrf = await client.get(CSRF, headers=headers)
    assert csrf.status_code == 401 and "SESSION_EXPIRED" not in csrf.text
    result = await client.post(LOGOUT, headers=headers)
    assert result.status_code == 201 and "next_action" not in result.text
    idp.introspect.assert_not_awaited()


async def test_disabled_runtime_assembles_local_protocol_without_oidc_or_directory_credentials(monkeypatch):
    from types import SimpleNamespace

    from bisheng.common.services import config_service
    from bisheng.sso_sync.application.runtime import KunlianRuntimeProvider
    from test.sso.test_kunlian_admission import config

    cfg = config()
    cfg.login_enabled = cfg.directory_enabled = False
    settings = SimpleNamespace(
        sso_sync=SimpleNamespace(kunlian=cfg), multi_tenant=SimpleNamespace(enabled=False), aget_from_db=AsyncMock()
    )
    monkeypatch.setattr(config_service, "settings", settings)
    provider = KunlianRuntimeProvider(
        secret_resolver={cfg.csrf_secret_reference: SecretStr("fixture-csrf-only")}.__getitem__
    )
    try:
        bindings = await provider.api_bindings()
        browser = await provider.browser_application()
        assert bindings.login is None and browser.sessions is None and provider._idp is None
        assert bindings.protocol is not None and browser.protocol is bindings.protocol
        assert bindings.protocol.service.sessions.idp_client is None
        settings.aget_from_db.assert_not_awaited()
    finally:
        await provider.aclose()


async def test_local_protocol_cannot_satisfy_business_user_dependency(logout_api):
    from bisheng.common.dependencies.user_deps import UserPayload

    client, _, _, _, _, headers = logout_api
    app = client._transport.app
    app.router.routes = [route for route in app.router.routes if getattr(route, "path", None) != CSRF]

    @app.get(CSRF)
    async def miswired(request: Request):
        await UserPayload.get_login_user(http_tests.auth(request))
        return {"unexpected": "business identity"}

    # 错误的业务依赖不得把已验证的本地协议变成业务身份。
    from bisheng.common.errcode.sso_sync import KunlianError

    @app.exception_handler(KunlianError)
    async def rejected(request, error):
        return error.to_response()

    result = await client.get(CSRF, headers=headers)
    assert result.status_code == 403 and "unexpected" not in result.text


async def test_bounded_expiry_clears_short_receipts_and_does_not_wait_for_new_browser_requests(session_store):
    repository, sessions, clock, bindings = session_store
    issued = await store_tests.issue(repository, clock, bindings[0])
    from bisheng.sso_sync.domain.models.kunlian import KunlianHandoffReceipt

    await store_tests.issue(repository, clock, bindings[0], "handoff-2")
    clock.advance(61)
    assert await repository.expire_handoff_material("fixture", limit=1) == 1
    assert await repository.expire_handoff_material("fixture", limit=1) == 1
    assert await repository.expire_handoff_material("fixture", limit=1) == 0
    async with sessions() as sql:
        receipt = await sql.get(KunlianHandoffReceipt, "handoff-1")
        assert receipt.session_ref_ciphertext == "" and receipt.signing_context["user_id"] == 101
        assert (await sql.get(KunlianWebSession, issued.session_hash)).id_token_ciphertext
    clock.advance(3600)
    assert await repository.expire_sessions("fixture", limit=1) == 1
    assert await repository.expire_sessions("fixture", limit=1) == 1
    assert await repository.expire_sessions("fixture", limit=1) == 0
    async with sessions() as sql:
        web = await sql.get(KunlianWebSession, issued.session_hash)
        assert web.state == "EXPIRED" and web.id_token_ciphertext == web.access_token_ciphertext == ""
