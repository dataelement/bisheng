"""AC-IDLE-01/02/05/07: HTTP flow with real PKCE, tickets, JWTs, SQL and old wire fields.

This is an in-process API chain, not production middleware or a packaged Electron E2E.
The browser identity and supplier are isolated fixtures. DSH intentionally returns
raw JSON with real HTTP statuses, not the platform UnifiedResponseModel.
"""

import base64
import hashlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from bisheng.dsh.access_runtime import get_logout_runtime, get_runtime
from bisheng.dsh.api.endpoints import identity, local_auth, models
from test.dsh import test_idle_sessions as idle_tests
from test.dsh import test_model_service as model_tests

native = idle_tests.native
idle = idle_tests.idle
service_setup = model_tests.service_setup


@pytest.fixture
def http_idle(idle, service_setup, monkeypatch):
    runtime, engine, clock = idle
    model, llm, ledger, _policy, _state = service_setup
    # Quota and supplier are external boundaries; lifecycle/SQL/PKCE remain real.
    ledger.check_and_start = AsyncMock(side_effect=lambda event, **_kwargs: event)
    model_runtime = SimpleNamespace(model=model, complete=model.complete)
    monkeypatch.setattr(models, "get_model_runtime", AsyncMock(return_value=model_runtime))

    class ServerClock(datetime):
        @classmethod
        def now(cls, tz=None):
            value = clock[0].replace(tzinfo=UTC)
            return value.astimezone(tz) if tz else value.replace(tzinfo=None)

    monkeypatch.setattr("jwt.api_jwt.datetime", ServerClock)
    app = FastAPI()
    app.include_router(local_auth.router, prefix="/api/v1")
    app.include_router(local_auth.router, prefix="/api")
    app.include_router(identity.router, prefix="/api/v1")
    app.include_router(models.router, prefix="/api/v1")
    app.dependency_overrides[get_runtime] = lambda: runtime
    app.dependency_overrides[get_logout_runtime] = lambda: runtime
    app.dependency_overrides[identity.browser_user] = lambda: SimpleNamespace(tenant_id=2, user_id=20)
    return app, runtime, engine, clock, llm


async def browser_login(client, prefix):
    verifier = "v" * 43
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    started = await client.post(
        prefix + "/authorizations",
        json={
            "client_id": "dsh-desktop",
            "redirect_uri": "http://127.0.0.1:49152/dsh/callback",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "s" * 32,
            "client_version": "1.2.0",
            "device_name": "e2e-idle-device",
        },
    )
    assert started.status_code == 200
    auth_id = started.json()["auth_id"]
    # Same browser confirmation and one-time code used by callback and paste flows.
    confirmed = await client.post(
        "/api/v1/dsh/authorize",
        json={"auth_id": auth_id},
        headers={"Origin": "https://platform.example"},
    )
    assert confirmed.status_code == 200
    ticket = confirmed.json()["data"]["identity_ticket"]
    exchanged = await client.post(
        prefix + "/token",
        json={
            "grant_type": "identity_ticket",
            "identity_ticket": ticket,
            "auth_id": auth_id,
            "code_verifier": verifier,
        },
    )
    assert exchanged.status_code == 200
    assert "status_code" not in exchanged.json()
    assert exchanged.headers["cache-control"] == "no-store"
    return exchanged.json()


async def refresh(client, prefix, token):
    return await client.post(prefix + "/token", json={"grant_type": "refresh_token", "refresh_token": token})


@pytest.mark.parametrize("prefix", ["/api/v1/dsh", "/api/dsh"])
async def test_old_login_fields_and_alias_survive_sliding_business_activity(http_idle, prefix):
    """AC-IDLE-01/03/07: old login and paste payloads obtain moving deadlines."""
    app, _runtime, engine, clock, llm = http_idle
    start = clock[0]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="https://platform.example") as client:
        issued = await browser_login(client, prefix)
        assert issued["refresh_expires_in"] == 14 * 86400
        clock[0] = start + timedelta(days=13)
        current = (await refresh(client, prefix, issued["refresh_token"])).json()
        headers = {"Authorization": "Bearer " + current["access_token"]}
        assert (await client.get("/api/v1/dsh/models", headers=headers)).status_code == 200
        assert (await client.get("/api/v1/dsh/profile", headers=headers)).status_code == 200
        assert idle_tests.stored(engine, issued).last_activity_at == start
        completed = await client.post(
            "/api/v1/dsh/chat/completions",
            headers=headers,
            json={
                "model": "bisheng:42",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert completed.status_code == 200
        assert llm.calls == 1
        renewed = idle_tests.stored(engine, issued)
        assert renewed.last_activity_at == clock[0]
        assert renewed.expires_at == clock[0] + timedelta(days=14)
        # The same old wire response synchronizes the deadline on the next refresh.
        current = (await refresh(client, prefix, current["refresh_token"])).json()
        assert current["refresh_expires_in"] == 14 * 86400
        assert current["session_expires_at"] != issued["session_expires_at"]
        assert set(current) == set(issued)
        clock[0] = start + timedelta(days=20)
        assert (await refresh(client, prefix, current["refresh_token"])).status_code == 200


async def test_background_only_device_expires_and_other_device_is_independent(http_idle):
    """AC-IDLE-02/05: refresh polling is not activity and logout is per grant."""
    app, runtime, engine, clock, _llm = http_idle
    start = clock[0]
    prefix = "/api/v1/dsh"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="https://platform.example") as client:
        first, second = await browser_login(client, prefix), await browser_login(client, prefix)
        clock[0] = start + timedelta(days=13)
        second_current = (await refresh(client, prefix, second["refresh_token"])).json()
        await runtime.sessions.record_activity(idle_tests.actor(first))
        clock[0] = start + timedelta(days=14)
        denied = await refresh(client, prefix, second_current["refresh_token"])
        assert denied.status_code == 401
        assert denied.json()["error"]["code"] == "session_expired"
        first_current = (await refresh(client, prefix, first["refresh_token"])).json()
        assert idle_tests.stored(engine, second).last_activity_at == start
        exited = await client.post(prefix + "/logout", json={"refresh_token": first_current["refresh_token"]})
        assert exited.status_code == 204
        assert (await refresh(client, prefix, first_current["refresh_token"])).json()["error"][
            "code"
        ] == "session_revoked"
