"""New and legacy Desktop consumers share their original API contracts.

SQLite exercises persisted ownership and tenant filtering, not production row locks.
"""

from contextlib import contextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import APIRouter, Depends, FastAPI
from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from bisheng.app_runtime.domain.services import desktop_apps_service
from bisheng.app_runtime.domain.services.desktop_apps_service import DesktopAppsService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.platform_auth import PlatformAuthError
from bisheng.common.services.config_service import settings
from bisheng.core.database import tenant_filter
from bisheng.dsh.api.dependencies import desktop_principal, get_runtime
from bisheng.dsh.api.endpoints import apps, self_service
from bisheng.dsh.api.responses import DshRoute
from bisheng.dsh.domain.models.local_session import DshRefreshToken, DshSession
from bisheng.dsh.domain.repositories.local_session import DshSessionRepository
from bisheng.dsh.domain.schemas.contracts import DshIdentitySnapshot, DshTenantDisplay, DshUserDisplay
from bisheng.dsh.domain.services.access import DshAccessService
from bisheng.dsh.domain.services.local_session import DshLocalSessionService
from bisheng.user.domain.models.platform_session import PlatformRefreshToken, PlatformSession, PlatformWebTicket
from bisheng.user.domain.repositories.platform_session import PlatformSessionRepository
from bisheng.user.domain.services.platform_session import PlatformSessionService


@pytest.fixture
def desktop(tmp_path, monkeypatch):
    monkeypatch.setattr(settings.multi_tenant, "enabled", True)
    monkeypatch.setattr(tenant_filter, "_force_import_all_models", lambda: None)
    monkeypatch.setattr(tenant_filter, "_tenant_aware_tables", set(tenant_filter._tenant_aware_tables))
    initialized = tenant_filter._initialized
    with Session() as probe:
        previous = {name: set(getattr(probe.dispatch, name)) for name in ("do_orm_execute", "before_flush")}
    tenant_filter.register_tenant_filter_events()
    tenant_filter._tenant_aware_tables.update(
        {"platform_session", "platform_refresh_token", "dsh_session", "dsh_refresh_token"}
    )
    engine = create_engine(f"sqlite:///{tmp_path}/desktop.db")
    SQLModel.metadata.create_all(
        engine,
        tables=[
            m.__table__ for m in (PlatformSession, PlatformRefreshToken, PlatformWebTicket, DshSession, DshRefreshToken)
        ],
    )
    clock = [datetime.utcnow()]

    class Repo(PlatformSessionRepository):
        def identity(self, user_id, tenant_id, **kwargs):
            return {
                "id": user_id,
                "user_name": "alice",
                "tenant_id": tenant_id,
                "tenant_name": "Home",
                "token_version": 0,
            }

    @contextmanager
    def platform_scope():
        with Session(engine) as db, db.begin():
            yield Repo(db)

    @contextmanager
    def legacy_scope():
        with Session(engine) as db, db.begin():
            yield DshSessionRepository(db)

    platform = PlatformSessionService(platform_scope, secret="isolated-desktop-consumer-test", now=lambda: clock[0])
    identity = DshIdentitySnapshot(
        active=True,
        tenant_id="9",
        user_id="7",
        profile_version=0,
        user=DshUserDisplay(id="7", username="alice", display_name="Alice"),
        tenant=DshTenantDisplay(id="9", name="Home"),
    )
    identities = SimpleNamespace(check=AsyncMock(return_value=identity))
    keys = SimpleNamespace(resolve=AsyncMock(return_value=b"isolated-desktop-consumer-key-32bytes"))
    legacy = DshLocalSessionService(legacy_scope, identities, keys, now=lambda: clock[0])
    runtime = SimpleNamespace(
        access=DshAccessService("bisheng-dsh", keys, identities, legacy, platform_auth=platform),
        sessions=legacy,
        platform_sessions=platform,
        identity=identities,
        settings=SimpleNamespace(platform_public_url="http://test"),
    )
    app = FastAPI()
    app.dependency_overrides[get_runtime] = lambda: runtime
    app.dependency_overrides[UserPayload.get_login_user] = lambda: SimpleNamespace(user_id=7, tenant_id=9)
    app.include_router(self_service.router, prefix="/api/v1")
    manager = self_service.DshSelfService(runtime)
    app.dependency_overrides[self_service.self_service] = lambda: manager
    monkeypatch.setattr(manager, "identity", AsyncMock(return_value=identity))
    yield SimpleNamespace(app=app, runtime=runtime, platform=platform, clock=clock, identity=identity)
    engine.dispose()
    with Session() as probe:
        for name, listeners in previous.items():
            for listener in set(getattr(probe.dispatch, name)) - listeners:
                event.remove(Session, name, listener)
    tenant_filter._initialized = initialized


def client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def legacy_login(desktop):
    return await desktop.runtime.sessions.exchange(desktop.identity, str(uuid4()), {"device_name": "Old Desktop"})


@pytest.mark.parametrize("kind", ["platform", "legacy"])
async def test_desktop_apps_list_launch_and_deploy_limits_accept_both_sessions(desktop, monkeypatch, kind):
    issued = (
        await desktop.platform.issue(7, 9, "bisheng-desktop") if kind == "platform" else await legacy_login(desktop)
    )
    app = SimpleNamespace(
        id="a" * 32, tenant_id=9, state="online", name="App", slug="app", description="", current_version_id="b" * 32
    )
    repository = SimpleNamespace(get=AsyncMock(return_value=app), page=AsyncMock(return_value=([app], None)))
    tickets = SimpleNamespace(issue=AsyncMock(return_value="t" * 43))
    service = DesktopAppsService(desktop.runtime, repository, tickets)
    desktop.app.dependency_overrides[apps.app_service] = lambda: service
    desktop.app.include_router(apps.router, prefix="/api/v1")
    monkeypatch.setattr(desktop_apps_service, "current_global_super", AsyncMock(return_value=False))
    monkeypatch.setattr(desktop_apps_service, "check_action", AsyncMock(return_value=True))
    require = AsyncMock()
    monkeypatch.setattr(desktop_apps_service, "require_action", require)
    headers = {"Authorization": "Bearer " + issued["access_token"]}
    async with client(desktop.app) as http:
        listed = await http.get("/api/v1/dsh/apps", headers=headers)
        assert listed.status_code == 200
        assert listed.json()["data"]["items"][0]["id"] == app.id
        launched = await http.post(f"/api/v1/dsh/apps/{app.id}/launch", headers=headers)
        assert launched.status_code == 200
        assert launched.json()["data"]["ticket"] == "t" * 43
        assert (await http.get("/api/v1/dsh/apps/deploy-limits", headers=headers)).status_code == 200
        principal = tickets.issue.await_args.args[0]
        if kind == "platform":
            await desktop.platform.logout(issued["access_token"])
        else:
            await desktop.runtime.sessions.revoke(9, 7, issued["session_id"])
        # Also cover cached principals re-entering the app service after revocation.
        from bisheng.common.errcode.dsh import DshSessionRevokedError

        with pytest.raises(DshSessionRevokedError):
            await service.actor(principal)
        assert (await http.get("/api/v1/dsh/apps", headers=headers)).status_code == 401
    assert require.await_args.kwargs["action"] == "visible"


async def test_device_manager_pages_new_and_old_sessions_without_other_subjects(desktop):
    expected = []
    for _ in range(4):
        expected.append((await desktop.platform.issue(7, 9, "bisheng-desktop"))["session_id"])
        expected.append((await legacy_login(desktop))["session_id"])
    await desktop.platform.issue(8, 9, "bisheng-desktop")
    await desktop.platform.issue(7, 10, "bisheng-desktop")
    await desktop.platform.issue(7, 9, "bisheng-web")
    await desktop.platform.issue(7, 9, "bisheng-mobile")
    cursor, seen = None, []
    async with client(desktop.app) as http:
        while True:
            params = {"limit": 3, **({"cursor": cursor} if cursor else {})}
            response = await http.get("/api/v1/dsh/me/sessions", params=params)
            assert response.status_code == 200
            page = response.json()["data"]
            for row in page["items"]:
                assert set(row) == {
                    "session_id",
                    "device_label",
                    "client_version",
                    "state",
                    "expires_at",
                    "created_at",
                    "last_seen_at",
                }
                seen.append(row["session_id"])
            if not page["has_more"]:
                assert page["next_cursor"] is None
                break
            assert page["next_cursor"] and page["next_cursor"] != cursor
            cursor = page["next_cursor"]
    assert seen == sorted(expected)


@pytest.mark.parametrize("kind", ["platform", "legacy"])
async def test_device_manager_revoke_is_idempotent_and_blocks_refresh(desktop, kind):
    issued = (
        await desktop.platform.issue(7, 9, "bisheng-desktop") if kind == "platform" else await legacy_login(desktop)
    )
    async with client(desktop.app) as http:
        for _ in range(2):
            response = await http.post(
                f"/api/v1/dsh/me/sessions/{issued['session_id']}/revoke", headers={"Origin": "http://test"}, json={}
            )
            assert response.status_code == 200
            assert response.json()["data"] == {"session_id": issued["session_id"], "state": "REVOKED"}
    if kind == "platform":
        with pytest.raises(PlatformAuthError, match="session_revoked"):
            await desktop.platform.refresh(issued["refresh_token"])
    else:
        from bisheng.common.errcode.dsh import DshSessionRevokedError

        desktop.runtime.sessions.keys.resolve_refresh_successor_key = AsyncMock(return_value=b"test-successor-key")
        with pytest.raises(DshSessionRevokedError):
            await desktop.runtime.sessions.refresh(issued["refresh_token"])


@pytest.mark.parametrize(
    "user,tenant,kind",
    [(8, 9, "bisheng-desktop"), (7, 10, "bisheng-desktop"), (7, 9, "bisheng-web"), (7, 9, "bisheng-mobile")],
)
async def test_device_manager_refuses_foreign_or_non_desktop_sessions(desktop, user, tenant, kind):
    issued = await desktop.platform.issue(user, tenant, kind)
    async with client(desktop.app) as http:
        response = await http.post(
            f"/api/v1/dsh/me/sessions/{issued['session_id']}/revoke", headers={"Origin": "http://test"}, json={}
        )
        assert response.status_code == 401
    await desktop.platform.inspect(issued["access_token"])


@pytest.mark.parametrize(
    "failure,expected_status,expected_code",
    [
        ("expired", 401, "session_expired"),
        ("revoked", 401, "session_revoked"),
        ("storage", 503, "authorization_unavailable"),
    ],
)
async def test_platform_failures_keep_dsh_http_contract(desktop, monkeypatch, failure, expected_status, expected_code):
    issued = await desktop.platform.issue(7, 9, "bisheng-desktop")
    router = APIRouter(route_class=DshRoute)

    @router.get("/probe")
    async def probe(principal=Depends(desktop_principal)):
        return {"ok": True}

    desktop.app.include_router(router)
    if failure == "expired":
        desktop.clock[0] += timedelta(days=31)
    elif failure == "revoked":
        await desktop.platform.logout(issued["access_token"])
    else:
        monkeypatch.setattr(
            desktop.platform, "inspect", AsyncMock(side_effect=PlatformAuthError("auth_service_unavailable"))
        )
    async with client(desktop.app) as http:
        response = await http.get("/probe", headers={"Authorization": "Bearer " + issued["access_token"]})
    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == expected_code
    assert response.headers["cache-control"] == "no-store"
    if failure == "expired":
        assert (await desktop.platform.refresh(issued["refresh_token"]))["access_token"]
