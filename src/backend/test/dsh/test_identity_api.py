"""F062 HTTP identity boundary. 覆盖 AC: AC-01, AC-02, AC-03, AC-04, AC-13, AC-30, AC-31, AC-32."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from bisheng.dsh.api.dependencies import get_runtime, get_settings
from bisheng.dsh.api.endpoints.identity import browser_user, router
from bisheng.dsh.config import DshSettings
from bisheng.dsh.domain.schemas.contracts import DshIdentitySnapshot


@pytest.fixture
def http_app():
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    runtime = SimpleNamespace(
        settings=SimpleNamespace(platform_public_url="https://bisheng.example", installation_id="i"),
        identity=SimpleNamespace(
            authorize=AsyncMock(
                return_value={
                    "identity_ticket": "test",
                    "redirect_uri": "http://127.0.0.1:123/dsh/callback",
                    "state": "s",
                    "expires_in": 60,
                }
            ),
            check=AsyncMock(
                return_value=DshIdentitySnapshot(
                    installation_id="i", tenant_id="2", user_id="1", active=False, reason="user_disabled"
                )
            ),
        ),
        inbound_auth=SimpleNamespace(verify=AsyncMock(return_value="i")),
    )
    app.dependency_overrides[get_settings] = lambda: DshSettings()
    app.dependency_overrides[get_runtime] = lambda: runtime
    app.dependency_overrides[browser_user] = lambda: SimpleNamespace(user_id=1, tenant_id=2)
    return app, runtime


async def test_disabled_probe_does_not_construct_runtime(http_app):
    app, _ = http_app

    def fail():
        raise AssertionError("Disabled discovery must not build dependencies")

    app.dependency_overrides[get_runtime] = fail
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://bisheng.example") as client:
        response = await client.get("/api/v1/dsh/config")
        assert response.json() == {"enabled": False}
        assert response.headers["cache-control"] == "no-store"


async def test_browser_requires_matching_origin_and_refuses_body_identity(http_app):
    app, runtime = http_app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://bisheng.example") as client:
        for headers in (
            {},
            {"Origin": "https://evil.example"},
            {"Origin": "https://bisheng.example", "Sec-Fetch-Site": "cross-site"},
        ):
            assert (
                await client.post("/api/v1/dsh/authorize", json={"auth_id": "a"}, headers=headers)
            ).status_code == 403
        response = await client.post(
            "/api/v1/dsh/authorize",
            json={"auth_id": "a", "user_id": "999"},
            headers={"Origin": "https://bisheng.example"},
        )
        assert response.status_code == 400
        assert runtime.identity.authorize.await_count == 0
        response = await client.post(
            "/api/v1/dsh/authorize", json={"auth_id": "a"}, headers={"Origin": "https://bisheng.example"}
        )
        assert response.json()["data"]["identity_ticket"] == "test"
        assert response.headers["referrer-policy"] == "no-referrer"
        identity = runtime.identity.authorize.call_args.args[0]
        assert identity.user_id == "1" and identity.tenant_id == "2"


async def test_internal_endpoint_requires_service_headers_and_instance_binding(http_app):
    app, _runtime = http_app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://bisheng.example") as client:
        response = await client.post(
            "/api/v1/internal/dsh/identity/check",
            json={"installation_id": "i", "tenant_id": "2", "user_id": "1"},
            headers={"Authorization": "Bearer ordinary-jwt"},
        )
        assert response.status_code == 401
        headers = {
            "X-DSH-Installation-Id": "i",
            "X-DSH-Key-Id": "k",
            "X-DSH-Timestamp": "1",
            "X-DSH-Nonce": "n",
            "X-DSH-Signature": "s",
        }
        response = await client.post(
            "/api/v1/internal/dsh/identity/check",
            json={"installation_id": "other", "tenant_id": "2", "user_id": "1"},
            headers=headers,
        )
        assert response.status_code == 401
        response = await client.post(
            "/api/v1/internal/dsh/identity/check",
            json={"installation_id": "i", "tenant_id": "2", "user_id": "1"},
            headers=headers,
        )
        assert response.status_code == 200 and response.json()["active"] is False
        assert "data" not in response.json()


async def test_internal_http_hmac_body_and_replay_with_real_redis(http_app, dsh_redis_url):
    import json

    from redis.asyncio import Redis

    from bisheng.dsh.infrastructure.service_auth import RedisNonceStore, ServiceAuth, ServiceKey

    app, runtime = http_app
    redis = Redis.from_url(dsh_redis_url)
    auth = ServiceAuth(ServiceKey("i", "gateway-test", b"s" * 32), RedisNonceStore(redis))
    runtime.inbound_auth = auth
    path = "/api/v1/internal/dsh/identity/check"
    body = json.dumps({"installation_id": "i", "tenant_id": "2", "user_id": "1"}).encode()
    headers = {**auth.sign("POST", path, body), "Content-Type": "application/json"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://bisheng.example") as client:
        assert (await client.post(path, content=body, headers=headers)).status_code == 200
        assert (await client.post(path, content=body, headers=headers)).status_code == 401
        headers = {**auth.sign("POST", path, body), "Content-Type": "application/json"}
        assert (await client.post(path, content=body.replace(b'"2"', b'"3"'), headers=headers)).status_code == 401
    await redis.aclose()
