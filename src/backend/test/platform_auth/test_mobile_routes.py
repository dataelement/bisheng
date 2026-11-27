"""Actual mobile route wiring with SQL authentication and a fake desktop transport."""

import asyncio
from datetime import timedelta
from types import SimpleNamespace

from fastapi import APIRouter, FastAPI, Request
from httpx import ASGITransport, AsyncClient

from test.platform_auth.test_platform_session import runtime as _runtime
from test.platform_auth.test_platform_stream import reference
from test.platform_auth.test_platform_wiring import settings_env as _settings_env

runtime = _runtime
settings_env = _settings_env


def mobile_app(service, issued, monkeypatch):
    from bisheng.admin.application import request_admission
    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.dsh.api.endpoints import mobile
    from bisheng.dsh.domain.services.mobile_access import MobileAccessService
    from bisheng.user.domain.services import platform_stream
    from bisheng.user.domain.services.platform_identity import PlatformActivity

    class DesktopStore:
        def __init__(self):
            self.dispatched = []

        async def read(self, desktop_id):
            return SimpleNamespace(user_id="7", tenant_id="9")

        async def current_connection(self, desktop_id):
            return "unit-desktop-connection"

        async def push_request(self, desktop_id, connection_id, body):
            self.dispatched.append(body)

        async def pop_response(self, *args):
            return {"status": 200, "body": '{"ok":true}', "contentType": "application/json"}

    store = DesktopStore()
    transport = MobileAccessService(store)
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    subset = APIRouter()
    paths = {"/dsh/mobile/desktops/{desktop_id}/rpc", "/dsh/mobile/desktops/{desktop_id}/session/stream"}
    subset.routes.extend(route for route in mobile.router.routes if route.path in paths)
    app.include_router(subset, prefix="/api/v1")
    app.state.platform_auth_service = service
    app.dependency_overrides[mobile.mobile_service] = lambda: transport
    actor = SimpleNamespace(
        user_id=7,
        user_name="unit-platform-mobile",
        tenant_id=9,
        token_version=0,
        is_global_super=False,
        _runtime_credential_reference=reference(service, issued),
    )

    async def authenticate(connection):
        await service.inspect(issued["access_token"])
        connection.state.authenticated_activity = PlatformActivity(service, issued["access_token"])
        return actor

    async def dependency(request: Request):
        return request.state.admitted_login_user

    monkeypatch.setattr(request_admission, "authenticate_browser", authenticate)
    original_guard = platform_stream.run_platform_guarded

    async def fast_guard(*args, **kwargs):
        return await original_guard(*args, **kwargs, interval=0.01, budget=0.1)

    monkeypatch.setattr(platform_stream, "run_platform_guarded", fast_guard)
    app.dependency_overrides[UserPayload.get_login_user] = dependency
    request_admission.install_request_admission(app)
    return app, transport, store


async def test_actual_mobile_rpc_business_method_renews_but_list_does_not(runtime, settings_env, monkeypatch):
    """AC-07/26: The real mobile RPC route counts prompt activity after desktop ownership admission."""
    service, clock, _ = runtime
    issued = await service.issue(7, 9, "bisheng-mobile")
    app, _, store = mobile_app(service, issued, monkeypatch)
    clock[0] += timedelta(days=20)
    path = "/api/v1/dsh/mobile/desktops/" + "d" * 32 + "/rpc"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://platform.test") as client:
        listed = await client.post(path, json={"method": "session.list", "payload": {}})
        assert listed.status_code == 200
        unchanged = await service.inspect(issued["access_token"])
        assert unchanged["session_expires_at"] == issued["session_expires_at"]
        prompted = await client.post(
            path,
            json={
                "method": "session.prompt",
                "payload": {"sessionId": "unit-session", "content": [{"type": "text", "text": "unit prompt"}]},
            },
        )
        assert prompted.status_code == 200
        renewed = await service.inspect(issued["access_token"])
        assert renewed["session_expires_at"] != issued["session_expires_at"]
        assert len(store.dispatched) == 2


async def test_actual_mobile_sse_route_closes_on_parent_logout(runtime, settings_env, monkeypatch):
    """AC-16/26: The actual mobile SSE route retains the bounded platform guard."""
    from bisheng.dsh.domain.services.mobile_access import MobileStream

    service, _, _ = runtime
    issued = await service.issue(7, 9, "bisheng-mobile")
    app, transport, _ = mobile_app(service, issued, monkeypatch)
    opened, blocked, closed = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def body():
        yield "event: ready\ndata: {}\n\n"
        opened.set()
        await blocked.wait()

    async def close():
        closed.set()

    async def open_stream(*args):
        return MobileStream(200, "text/event-stream", body(), close)

    monkeypatch.setattr(transport, "open_session_stream", open_stream)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://platform.test") as client:
        response_task = asyncio.create_task(
            client.get("/api/v1/dsh/mobile/desktops/" + "d" * 32 + "/session/stream?sessionId=unit-session")
        )
        await opened.wait()
        await service.logout(issued["access_token"])
        result = await asyncio.wait_for(response_task, timeout=1)
        assert "session_revoked" in result.text and "event: error" in result.text
        assert closed.is_set()
