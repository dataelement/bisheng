"""Real HTTP + SQL + signed JWT contract tests (no external identity service)."""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.responses import JSONResponse

from bisheng.common.errcode.platform_auth import PlatformAuthError
from bisheng.user.api.endpoints.platform_auth import router
from test.platform_auth.test_platform_session import runtime as _runtime

runtime = _runtime


def app_for(service):
    app = FastAPI()
    app.state.platform_auth_service = service
    app.state.platform_auth_settings = SimpleNamespace(public_origin=None, trusted_proxy_hosts=["127.0.0.1", "::1"])
    app.include_router(router, prefix="/api/v1")

    @app.exception_handler(PlatformAuthError)
    async def error(request, exc):
        return JSONResponse(exc.payload(), status_code=exc.http_status, headers={"Cache-Control": "no-store"})

    return app


@pytest.mark.parametrize("native_client", ["bisheng-mobile", "bisheng-desktop"])
async def test_native_http_rotate_and_logout(runtime, native_client):
    """AC-01/08/15: Native wire tokens rotate and logout is authoritative."""
    service, _, _ = runtime
    first = await service.issue(7, 9, native_client)
    async with AsyncClient(transport=ASGITransport(app=app_for(service)), base_url="https://platform.test") as client:
        result = await client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
        assert result.status_code == 200
        second = result.json()["data"]
        assert "refresh_token" in second
        assert result.headers["cache-control"] == "no-store"
        state = await client.get("/api/v1/auth/session", headers={"Authorization": f"Bearer {second['access_token']}"})
        assert state.json()["data"]["session_id"] == first["session_id"]
        assert "access_token" not in state.json()["data"]
        assert (
            await client.post("/api/v1/auth/logout", json={"refresh_token": second["refresh_token"]})
        ).status_code == 200
        denied = await client.get("/api/v1/auth/session", headers={"Authorization": f"Bearer {second['access_token']}"})
        assert denied.status_code == 401
        assert denied.json()["data"]["auth_reason"] == "session_revoked"


async def test_web_pending_bootstrap_csrf_cookie_scope_and_conflict(runtime):
    """AC-03/11/23/27: Bind once with same-origin CSRF and scoped cookies."""
    service, _, _ = runtime
    pending = await service.issue(7, 9, "bisheng-web", pending=True)
    app = app_for(service)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://platform.test") as client:
        client.cookies.set("access_token_cookie", pending["access_token"], domain="platform.test", path="/")
        metadata = (await client.get("/api/v1/auth/session")).json()["data"]
        denied = await client.post("/api/v1/auth/web-bootstrap")
        assert denied.status_code == 403
        headers = {
            "Origin": "https://platform.test",
            "X-CSRF-Token": metadata["csrf_token"],
            "Sec-Fetch-Site": "same-origin",
        }
        result = await client.post("/api/v1/auth/web-bootstrap", headers=headers)
        assert result.status_code == 200
        assert "refresh_token" not in result.json()["data"]
        assert "access_token" not in result.json()["data"]
        sid = result.json()["data"]["session_id"]
        cookies = result.headers.get_list("set-cookie")
        issued_cookies = [c for c in cookies if c.startswith("platform_")]
        assert len(issued_cookies) == 2 and all(
            "HttpOnly" in c and "Secure" in c and "SameSite=lax" in c for c in issued_cookies
        )
        assert not any("platform_session_hint" in c for c in cookies)
        assert any("Path=/api/v1/auth" in c and "Max-Age=10454400" in c for c in cookies)
        client.cookies.set("platform_session_hint", sid)
        # Remove gateway entry after a completed bind, as the browser controller does.
        assert "access_token_cookie" in client.cookies
        conflict = await client.get(
            "/api/v1/auth/session", headers={"Authorization": f"Bearer {pending['access_token']}"}
        )
        assert conflict.status_code == 400
        rotated = await client.post("/api/v1/auth/refresh", headers=headers, json={})
        assert rotated.status_code == 200
        assert "refresh_token" not in rotated.json()["data"]
        cross_origin = await client.post(
            "/api/v1/auth/refresh", headers={**headers, "Origin": "https://evil.test"}, json={}
        )
        assert cross_origin.status_code == 403


@pytest.mark.parametrize("native_client", ["bisheng-mobile", "bisheng-desktop"])
async def test_ticket_is_single_use_and_parent_revocation_applies(runtime, native_client):
    """AC-15/26: Host delivery is one-use and never outlives its native parent."""
    service, _, _ = runtime
    parent = await service.issue(7, 9, native_client)
    async with AsyncClient(transport=ASGITransport(app=app_for(service)), base_url="https://platform.test") as client:
        ticket = (
            await client.post("/api/v1/auth/web-session", headers={"Authorization": f"Bearer {parent['access_token']}"})
        ).json()["data"]
        consumed = await client.get(ticket["consume_url"])
        assert consumed.status_code == 303 and consumed.headers["location"] == "/workspace"
        assert len(consumed.headers.get_list("set-cookie")) == 1
        assert (await client.get(ticket["consume_url"])).status_code == 401
        client.cookies.set("platform_session_hint", ticket["session_id"])
        state = await client.get("/api/v1/auth/session")
        assert state.json()["data"]["refresh_mode"] == "host"
        await service.logout(parent["access_token"])
        assert (await client.get("/api/v1/auth/session")).status_code == 401


async def test_access_cookie_missing_after_day_30_recovers_with_refresh_cookie(runtime):
    """AC-09: Browser expiry of the Access Cookie does not lose a live 90-day session."""
    service, clock, _ = runtime
    first = await service.issue(7, 9, "bisheng-web")
    async with AsyncClient(transport=ASGITransport(app=app_for(service)), base_url="https://platform.test") as client:
        sid = first["session_id"]
        client.cookies.set("platform_session_hint", sid)
        client.cookies.set(
            f"platform_refresh_{sid}", first["refresh_token"], domain="platform.test", path="/api/v1/auth"
        )
        clock[0] += timedelta(days=31)
        missing_access = await client.get("/api/v1/auth/session")
        assert missing_access.status_code == 401 and missing_access.json()["status_code"] == 10651
        csrf = (await client.get("/api/v1/auth/csrf")).json()["data"]["csrf_token"]
        headers = {"Origin": "https://platform.test", "X-CSRF-Token": csrf}
        refresh = await client.post("/api/v1/auth/refresh", json={}, headers=headers)
        assert refresh.status_code == 200
        session = await client.get("/api/v1/auth/session")
        assert session.status_code == 200 and session.json()["data"]["session_id"] == sid


async def test_cookie_logout_retry_is_idempotent_after_js_selection_cleared(runtime):
    """AC-15/28: Clearing the local hint first still allows CSRF-protected idempotent logout."""
    service, _, _ = runtime
    first = await service.issue(7, 9, "bisheng-web")
    sid = first["session_id"]
    cookies = {f"platform_access_{sid}": first["access_token"], f"platform_refresh_{sid}": first["refresh_token"]}
    raw_cookie = "; ".join(f"{key}={value}" for key, value in cookies.items())
    headers = {
        "Origin": "https://platform.test",
        "X-CSRF-Token": first["csrf_token"],
        "X-Platform-Session": sid,
        "Cookie": raw_cookie,
    }
    async with AsyncClient(transport=ASGITransport(app=app_for(service)), base_url="https://platform.test") as client:
        rejected = await client.post("/api/v1/auth/logout", headers={**headers, "Origin": "https://evil.test"})
        assert rejected.status_code == 403
        for _ in range(3):
            response = await client.post("/api/v1/auth/logout", headers=headers)
            assert response.status_code == 200
        denied = await client.get("/api/v1/auth/session", headers={"X-Platform-Session": sid, "Cookie": raw_cookie})
        assert denied.status_code == 401  # Header is never a business/session identity selector.


async def test_new_gateway_login_takes_precedence_and_late_bind_cannot_delete_it(runtime):
    """AC-14/23: A delayed bind only writes its own sid cookies, never another gateway entry."""
    service, clock, _ = runtime
    first = await service.issue(7, 9, "bisheng-web", pending=True)
    bound = await service.bootstrap(first["access_token"])
    clock[0] += timedelta(seconds=1)
    pending = await service.issue(7, 9, "bisheng-web", pending=True)
    async with AsyncClient(transport=ASGITransport(app=app_for(service)), base_url="https://platform.test") as client:
        client.cookies.set("platform_session_hint", bound["session_id"])
        client.cookies.set(f"platform_access_{bound['session_id']}", bound["access_token"])
        client.cookies.set("access_token_cookie", pending["access_token"])
        state = (await client.get("/api/v1/auth/session")).json()["data"]
        assert state["session_id"] == pending["session_id"] and state["delivery_state"] == "PENDING_WEB_BIND"
        delayed = await service.bootstrap(first["access_token"])
        from starlette.requests import Request
        from starlette.responses import Response

        from bisheng.user.domain.services.platform_transport import deliver

        response = Response()
        request = Request(
            {
                "type": "http",
                "scheme": "https",
                "server": ("platform.test", 443),
                "path": "/api/v1/auth/web-bootstrap",
                "headers": [],
                "app": app_for(service),
            }
        )
        deliver(response, request, delayed)
        assert all("access_token_cookie" not in c for c in response.headers.getlist("set-cookie"))
        assert client.cookies.get("access_token_cookie") == pending["access_token"]


@pytest.mark.parametrize(
    "path,body",
    [
        ("/refresh", {"refresh_token": 3}),
        ("/refresh", {"tenant_id": 9}),
        ("/login", {"user_name": "test"}),
        ("/login", {"user_name": "test", "password": "DO-NOT-LEAK", "user_id": 1}),
    ],
)
async def test_invalid_auth_body_is_real_400_and_does_not_echo_credentials(runtime, path, body):
    """AC-27/30: Closed inputs return 10663/400 without echoing secrets."""
    service, _, _ = runtime
    async with AsyncClient(transport=ASGITransport(app=app_for(service)), base_url="https://platform.test") as client:
        result = await client.post("/api/v1/auth" + path, json=body)
        assert result.status_code == 400 and result.json()["status_code"] == 10663
        assert result.json()["data"]["auth_reason"] == "invalid_auth_request"
        assert "DO-NOT-LEAK" not in result.text


@pytest.mark.parametrize("transport", ["cookie_and_body", "bearer_and_body"])
async def test_logout_rejects_conflicting_transports_without_revoking_either(runtime, transport):
    """AC-27: Conflicting logout proofs never silently select another session."""
    service, _, _ = runtime
    first = await service.issue(7, 9, "bisheng-mobile")
    other = await service.issue(7, 9, "bisheng-mobile")
    headers = {}
    if transport == "cookie_and_body":
        sid = first["session_id"]
        headers["Cookie"] = f"platform_session_hint={sid}; platform_refresh_{sid}={first['refresh_token']}"
    else:
        headers["Authorization"] = f"Bearer {first['access_token']}"
    async with AsyncClient(transport=ASGITransport(app=app_for(service)), base_url="https://platform.test") as client:
        response = await client.post(
            "/api/v1/auth/logout", json={"refresh_token": other["refresh_token"]}, headers=headers
        )
        assert response.status_code == 400 and response.json()["status_code"] == 10661
    await service.inspect(first["access_token"])
    await service.inspect(other["access_token"])


@pytest.mark.parametrize("allow_multi_login", [True, False])
async def test_lost_bootstrap_response_recovers_newer_bound_session_from_old_selection(runtime, allow_multi_login):
    """AC-11/23: Losing all bootstrap response cookies still recovers the unused first generation."""
    service, clock, _ = runtime
    service.allow_multi_login = allow_multi_login
    old = await service.issue(7, 9, "bisheng-web")
    entry = await service.issue(7, 9, "bisheng-web", pending=True)
    bound = await service.bootstrap(entry["access_token"])  # Transaction committed; entire HTTP response was lost.
    initial_cookie = f"platform_session_hint={old['session_id']}; platform_access_{old['session_id']}={old['access_token']}; access_token_cookie={entry['access_token']}"
    async with AsyncClient(transport=ASGITransport(app=app_for(service)), base_url="https://platform.test") as client:
        metadata_response = await client.get("/api/v1/auth/session", headers={"Cookie": initial_cookie})
        assert metadata_response.status_code == 200
        metadata = metadata_response.json()["data"]
        assert metadata["session_id"] == entry["session_id"] and metadata["delivery_state"] == "PENDING_WEB_BIND"
        recovered = await client.post(
            "/api/v1/auth/web-bootstrap",
            headers={
                "Cookie": initial_cookie,
                "Origin": "https://platform.test",
                "X-CSRF-Token": metadata["csrf_token"],
            },
        )
        assert recovered.status_code == 200
        assert client.cookies.get(f"platform_refresh_{entry['session_id']}") == bound["refresh_token"]
        assert "refresh_token" not in recovered.json()["data"]
        if allow_multi_login:
            newer = await service.issue(7, 9, "bisheng-web")
            newer_cookie = f"platform_session_hint={newer['session_id']}; platform_access_{newer['session_id']}={newer['access_token']}; access_token_cookie={entry['access_token']}"
            preferred = await client.get("/api/v1/auth/session", headers={"Cookie": newer_cookie})
            assert preferred.status_code == 200 and preferred.json()["data"]["session_id"] == newer["session_id"]
            # Another issuer may have an earlier clock; database order must
            # still protect its later selected session from the old fixed A.
            clock[0] -= timedelta(seconds=5)
            skewed = await service.issue(7, 9, "bisheng-web")
            skewed_cookie = f"platform_session_hint={skewed['session_id']}; platform_access_{skewed['session_id']}={skewed['access_token']}; access_token_cookie={entry['access_token']}"
            preferred = await client.get("/api/v1/auth/session", headers={"Cookie": skewed_cookie})
            assert preferred.status_code == 200 and preferred.json()["data"]["session_id"] == skewed["session_id"]
            assert "issuance_order" not in preferred.json()["data"]
            clock[0] += timedelta(seconds=5)
        await service.refresh(bound["refresh_token"])
        used = await client.get("/api/v1/auth/session", headers={"Cookie": initial_cookie})
        if allow_multi_login:
            assert used.status_code == 200 and used.json()["data"]["session_id"] == old["session_id"]
        else:
            assert used.status_code == 401 and used.json()["status_code"] == 10655
        clock[0] += timedelta(seconds=1)
        later = await service.issue(7, 9, "bisheng-web")
        later_cookie = f"platform_session_hint={later['session_id']}; platform_access_{later['session_id']}={later['access_token']}; access_token_cookie={entry['access_token']}"
        selected = await client.get("/api/v1/auth/session", headers={"Cookie": later_cookie})
        assert selected.status_code == 200 and selected.json()["data"]["session_id"] == later["session_id"]


async def test_refresh_cookie_retention_uses_each_session_policy_snapshot(runtime):
    """AC-05/06/14: Physical cookie retention follows frozen idle + access + one-day policy."""
    service, clock, _ = runtime
    default = await service.issue(7, 9, "bisheng-web")
    service.access_seconds, service.idle_seconds = 60 * 86400, 90 * 86400
    long_access = await service.issue(7, 9, "bisheng-web")
    service.access_seconds, service.idle_seconds = 30 * 86400, 180 * 86400
    long_idle = await service.issue(7, 9, "bisheng-web")
    # Further configuration updates must not shorten any existing session's
    # physical Cookie lifetime, including after actual activity extended it.
    service.access_seconds, service.idle_seconds = 86400, 86400
    clock[0] += timedelta(days=29)
    async with AsyncClient(transport=ASGITransport(app=app_for(service)), base_url="https://platform.test") as client:
        for issued, days in [(default, 121), (long_access, 151), (long_idle, 211)]:
            await service.activity(issued["access_token"])
            sid = issued["session_id"]
            cookie = f"platform_session_hint={sid}; platform_refresh_{sid}={issued['refresh_token']}"
            response = await client.post(
                "/api/v1/auth/refresh",
                json={},
                headers={"Cookie": cookie, "Origin": "https://platform.test", "X-CSRF-Token": issued["csrf_token"]},
            )
            assert response.status_code == 200
            assert response.json()["data"]["cookie_retention_seconds"] == days * 86400
            refresh_cookie = next(
                c for c in response.headers.get_list("set-cookie") if c.startswith(f"platform_refresh_{sid}=")
            )
            assert f"Max-Age={days * 86400}" in refresh_cookie
