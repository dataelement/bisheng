"""Always-on business settings with deployment and administrator boundaries."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.models.config import Config
from bisheng.dsh.api import dependencies
from bisheng.dsh.api.endpoints import identity, models
from bisheng.dsh.api.endpoints import settings as settings_api
from bisheng.dsh.config import DshSettings
from bisheng.dsh.domain.repositories import settings as settings_repo
from bisheng.dsh.domain.schemas.settings import DshManagementSettings
from bisheng.dsh.domain.services.settings import DshSettingsService


@pytest.fixture
async def settings_app(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/dsh-settings.db")
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: Config.__table__.create(sync))

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(engine) as session:
            yield session

    monkeypatch.setattr(settings_repo, "get_async_db_session", sessions)
    deployment = DshSettings(enabled=True, platform_public_url="http://test", gateway_internal_url="http://gateway")
    app = FastAPI()
    for router in (settings_api.router, identity.router, models.router):
        app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[dependencies.get_settings] = lambda: deployment
    app.dependency_overrides[settings_api.settings_admin] = lambda: SimpleNamespace(user_id=1)
    app.dependency_overrides[identity.browser_user] = lambda: SimpleNamespace(user_id=1, tenant_id=1)
    # Existing runtime resources are reused within the deployment boundary.
    app.state.dsh_runtime = SimpleNamespace(access=SimpleNamespace(authenticate=AsyncMock()))
    try:
        yield app, deployment, sessions
    finally:
        await engine.dispose()


async def test_always_enabled_settings_preserve_addresses_and_other_configuration(settings_app):
    app, deployment, sessions = settings_app
    async with sessions() as session:
        session.add(Config(key="other_config", value="keep"))
        session.add(Config(key="dsh_management", value='{"enabled":false,"download_url":null}'))
        await session.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/v1/dsh/config")).json()["enabled"] is True
        browser = await client.get("/api/v1/dsh/browser-config")
        assert browser.json()["data"]["enabled"] is True
        assert browser.headers["cache-control"] == "no-store"
        url = "/api/v1/dsh/admin/settings"
        value = {
            "enabled": False,
            "download_url": "http://downloads.test/desktop/latest",
            "launch_url": "dsh-desktop-test://login",
        }
        expected = {**value, "enabled": True}
        assert (await client.put(url, json=value)).json()["data"] == expected
        assert (await client.get(url)).json()["data"] == expected
        request = Request({"type": "http", "app": app})
        assert await dependencies.get_runtime(request, deployment) is app.state.dsh_runtime
    async with sessions() as session:
        rows = (await session.exec(select(Config))).all()
        assert {row.key for row in rows} == {"other_config", "dsh_management"}
        assert next(row.value for row in rows if row.key == "other_config") == "keep"
        assert DshManagementSettings.model_validate_json(
            next(row.value for row in rows if row.key == "dsh_management")
        ).enabled


async def test_deployment_gate_wins_without_reading_database(settings_app, monkeypatch):
    app, _, _ = settings_app
    app.dependency_overrides[dependencies.get_settings] = lambda: DshSettings()
    read = AsyncMock(side_effect=AssertionError("Deployment-off must not read business settings"))
    monkeypatch.setattr(DshSettingsService, "read", read)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/dsh/browser-config")
        assert response.json()["data"] == {
            "management_enabled": False,
            "enabled": False,
            "download_url": None,
            "launch_url": "dsh-desktop://login",
        }
        assert (await client.get("/api/v1/dsh/config")).json() == {"enabled": False}
        assert (await client.put("/api/v1/dsh/admin/settings", json={"enabled": True})).status_code == 403
    read.assert_not_awaited()


async def test_rejected_writes_leave_current_value_unchanged(settings_app):
    app, _, _ = settings_app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        for value in (
            "javascript:alert(1)",
            "//downloads.test/file",
            "http://user:secret@example.test/file",
            "http://host:bad/file",
        ):
            assert (
                await client.put("/api/v1/dsh/admin/settings", json={"enabled": True, "download_url": value})
            ).status_code == 400
        assert (await client.get("/api/v1/dsh/admin/settings")).json()["data"]["enabled"] is True

        def deny():
            raise HTTPException(403)

        app.dependency_overrides[settings_api.settings_admin] = deny
        assert (await client.put("/api/v1/dsh/admin/settings", json={"enabled": True})).status_code == 403
        assert (await DshSettingsService().read()).enabled


async def test_unreadable_settings_fail_closed():
    from bisheng.common.errcode.dsh import DshAuthorizationUnavailableError

    repository = SimpleNamespace(read=AsyncMock(return_value='{"enabled":"true"}'))
    with pytest.raises(DshAuthorizationUnavailableError):
        await DshSettingsService(repository).require_enabled()


def test_settings_reject_unknown_fields_and_normalize_empty_download():
    assert DshManagementSettings(download_url=" ").download_url is None
    with pytest.raises(ValidationError):
        DshManagementSettings(enabled=True, license="not-managed-here")


async def test_settings_use_existing_global_administrator_guard(monkeypatch):
    from bisheng.common.dependencies.user_deps import UserPayload

    user = SimpleNamespace(user_id=9, is_admin=lambda: False)
    monkeypatch.setattr(UserPayload, "get_login_user", AsyncMock(return_value=user))
    with pytest.raises(HTTPException) as denied:
        await settings_api.settings_admin(auth_jwt=object())
    assert denied.value.status_code == 403
    user.is_admin = lambda: True
    assert await settings_api.settings_admin(auth_jwt=object()) is user


@pytest.mark.parametrize(
    "value",
    [
        "javascript://alert",
        "data://text",
        "file://host/path",
        "https://site.test",
        "dsh-desktop://login?server=evil",
        "dsh-desktop://login#evil",
        "dsh-desktop://user:pass@login",
        "",
        None,
    ],
)
def test_launch_rejects_unsafe_or_non_base_urls(value):
    with pytest.raises(ValidationError):
        DshManagementSettings(launch_url=value)


async def test_existing_settings_default_launch_and_failed_writes_preserve_it(settings_app):
    app, _, sessions = settings_app
    async with sessions() as session:
        session.add(Config(key="dsh_management", value='{"enabled":true,"download_url":null}'))
        await session.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        url = "/api/v1/dsh/admin/settings"
        assert (await client.get(url)).json()["data"]["launch_url"] == "dsh-desktop://login"
        assert (await client.put(url, json={"enabled": True, "launch_url": "javascript://alert"})).status_code == 400
        assert (await client.get(url)).json()["data"]["launch_url"] == "dsh-desktop://login"
