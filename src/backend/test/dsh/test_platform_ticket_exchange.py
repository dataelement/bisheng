"""Browser PKCE tickets exchange into real unified Desktop platform sessions.

Redis cases require the explicitly isolated DSH_TEST_REDIS_URL fixture.
SQLite covers persistence transitions, not production row locking.
"""

import base64
import hashlib
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import jwt
import pytest
from fastapi import FastAPI
from redis.asyncio import Redis
from sqlmodel import Session, SQLModel, create_engine

from bisheng.dsh.access_runtime import get_logout_runtime, get_runtime
from bisheng.dsh.api.endpoints.local_auth import AuthorizationRequest, router
from bisheng.dsh.domain.repositories.tickets import TicketRepository
from bisheng.dsh.domain.schemas.identity import IdentityRecord
from bisheng.dsh.domain.services.authorization import DshAuthorizationService
from bisheng.dsh.domain.services.identity import BrowserIdentity, IdentityService
from bisheng.user.domain.models.platform_session import PlatformRefreshToken, PlatformSession, PlatformWebTicket
from bisheng.user.domain.repositories.platform_session import PlatformSessionRepository
from bisheng.user.domain.services.platform_session import PlatformSessionService


@pytest.fixture
def platform_app(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/desktop.db")
    SQLModel.metadata.create_all(
        engine, tables=[m.__table__ for m in (PlatformSession, PlatformRefreshToken, PlatformWebTicket)]
    )

    class Repo(PlatformSessionRepository):
        def identity(self, user_id, tenant_id, **kwargs):
            if (user_id, tenant_id) == (7, 9):
                return {"id": 7, "user_name": "alice", "tenant_id": 9, "tenant_name": "Enterprise", "token_version": 0}
            return None

    @contextmanager
    def scope():
        with Session(engine) as db, db.begin():
            yield Repo(db)

    service = PlatformSessionService(scope, secret="isolated-desktop-test-secret")
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.state.platform_auth_service = service
    runtime = SimpleNamespace(
        authorizations=SimpleNamespace(rate=AsyncMock()),
        sessions=SimpleNamespace(
            refresh=AsyncMock(return_value={"legacy": True}), logout_refresh=AsyncMock(), revoke=AsyncMock()
        ),
        access=SimpleNamespace(decode=AsyncMock()),
        identity=SimpleNamespace(
            profile=AsyncMock(
                return_value={
                    "user": {"id": "7", "username": "alice", "display_name": "Alice"},
                    "tenant": {"id": "9", "name": "Enterprise"},
                }
            )
        ),
    )
    app.dependency_overrides[get_runtime] = lambda: runtime
    app.dependency_overrides[get_logout_runtime] = lambda: runtime
    yield app, service, runtime
    engine.dispose()


async def test_real_pkce_one_time_ticket_issues_unified_refresh_and_logout(platform_app, dsh_redis_url):
    app, service, runtime = platform_app
    redis = Redis.from_url(dsh_redis_url, decode_responses=True)
    verifier = "v" * 64
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    authorizations = DshAuthorizationService(redis, "https://bisheng.example")

    class Records:
        async def get(self, tenant_id, user_id):
            if (tenant_id, user_id) == ("9", "7"):
                return IdentityRecord("9", "7", "alice", "Alice", "Enterprise", 0, True, True, True)
            return None

    runtime.authorizations = authorizations
    runtime.identity = IdentityService(TicketRepository(redis), Records(), authorizations)
    try:
        auth = await authorizations.create(
            AuthorizationRequest(
                client_id="dsh-desktop",
                redirect_uri="http://127.0.0.1:43211/dsh/callback",
                code_challenge=challenge,
                code_challenge_method="S256",
                state="s" * 32,
                device_name="My Desktop",
            )
        )
        consent = await runtime.identity.authorize(BrowserIdentity("9", "7"), auth["auth_id"])
        body = {
            "grant_type": "identity_ticket",
            "identity_ticket": consent["identity_ticket"],
            "auth_id": auth["auth_id"],
            "code_verifier": verifier,
        }
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://bisheng.example"
        ) as client:
            wrong = await client.post("/api/v1/dsh/token", json={**body, "code_verifier": "x" * 64})
            assert wrong.status_code == 400
            assert wrong.json()["error"]["code"] == "pkce_verification_failed"
            result = await client.post("/api/v1/dsh/token", json=body)
            assert result.status_code == 200
            data = result.json()
            assert data["user"] == {"id": "7", "username": "alice", "display_name": "Alice"}
            assert data["tenant"] == {"id": "9", "name": "Enterprise"}
            assert service.decode(data["access_token"])["client_id"] == "bisheng-desktop"
            assert (await client.post("/api/v1/dsh/token", json=body)).status_code == 400
            refreshed = await client.post(
                "/api/v1/dsh/token", json={"grant_type": "refresh_token", "refresh_token": data["refresh_token"]}
            )
            assert refreshed.status_code == 200
            assert refreshed.json()["session_id"] == data["session_id"]
            assert refreshed.json()["user"]["username"] == "alice"
            out = await client.post("/api/v1/dsh/logout", json={"refresh_token": refreshed.json()["refresh_token"]})
            assert out.status_code == 204
            denied = await client.post(
                "/api/v1/dsh/token",
                json={"grant_type": "refresh_token", "refresh_token": refreshed.json()["refresh_token"]},
            )
            assert denied.status_code == 401
            runtime.sessions.refresh.assert_not_awaited()
            runtime.sessions.logout_refresh.assert_not_awaited()
    finally:
        await redis.aclose()


async def test_platform_access_logout_and_tamper_never_fall_back(platform_app):
    app, service, runtime = platform_app
    issued = await service.issue(7, 9, "bisheng-desktop")
    forged = jwt.encode(
        {"session_id": issued["session_id"]},
        "wrong-signature",
        algorithm="HS256",
        headers={"typ": "bisheng-platform-access+jwt", "kid": "platform-access-v1"},
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://bisheng.example") as client:
        assert (
            await client.post("/api/v1/dsh/logout", headers={"Authorization": f"Bearer {forged}"})
        ).status_code == 401
        assert (
            await client.post("/api/v1/dsh/logout", headers={"Authorization": f"Bearer {issued['access_token']}"})
        ).status_code == 204
        denied = await client.post(
            "/api/v1/dsh/token", json={"grant_type": "refresh_token", "refresh_token": issued["refresh_token"]}
        )
        assert denied.status_code == 401
    runtime.access.decode.assert_not_awaited()
    runtime.sessions.revoke.assert_not_awaited()
    runtime.sessions.refresh.assert_not_awaited()


async def test_unowned_refresh_uses_legacy_validator(platform_app):
    app, _, runtime = platform_app
    credential = "L" * 43
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://bisheng.example") as client:
        result = await client.post(
            "/api/v1/dsh/token", json={"grant_type": "refresh_token", "refresh_token": credential}
        )
        assert result.json() == {"legacy": True}
        assert (await client.post("/api/v1/dsh/logout", json={"refresh_token": credential})).status_code == 204
    runtime.sessions.refresh.assert_awaited_once_with(credential)
    runtime.sessions.logout_refresh.assert_awaited_once_with(credential)
