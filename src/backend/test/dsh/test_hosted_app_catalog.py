"""v3.1.0-alpha1 F001 — the Desktop hosted-app catalog stays, every other Desktop-only capability answers 16149.

BISHENG Desktop 1.3.0 is released and still calls the retired routes; it reads
``status_message`` from a non-200 envelope, so the retired routes must keep
answering in the plain ``{status_code, status_message, data}`` shape.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bisheng.app_runtime.domain.services import desktop_apps_service as module
from bisheng.app_runtime.domain.services.desktop_apps_service import DesktopAppsService
from bisheng.common.errcode.app_factory import AppDesktopClientUpgradeRequiredError
from bisheng.common.errcode.dsh import DshInvalidAccessTokenError
from bisheng.dsh.api.dependencies import desktop_principal
from bisheng.dsh.api.endpoints import apps as endpoints
from bisheng.dsh.domain.services.access import DshPrincipal

APP_ID = "a" * 32


def _app(**overrides):
    row = {
        "id": APP_ID,
        "tenant_id": 2,
        "state": "online",
        "name": "Shared tasks",
        "slug": "shared-tasks",
        "description": "",
        "current_version_id": "b" * 32,
    }
    row.update(overrides)
    return SimpleNamespace(**row)


@pytest.fixture
def principal():
    return DshPrincipal(tenant_id="2", user_id="10", session_id="device-one")


@pytest.fixture
def service(monkeypatch):
    identity = SimpleNamespace(active=True, tenant_id="2", user_id="10", user=SimpleNamespace(username="alice"))
    runtime = SimpleNamespace(
        sessions=SimpleNamespace(validate=AsyncMock()), identity=SimpleNamespace(check=AsyncMock(return_value=identity))
    )
    repository = SimpleNamespace(page=AsyncMock(return_value=([_app()], None)))
    monkeypatch.setattr(module, "current_global_super", AsyncMock(return_value=False))
    monkeypatch.setattr(module, "check_action", AsyncMock(return_value=True))
    return DesktopAppsService(runtime, repository)


@pytest.fixture
def client(service, principal, monkeypatch):
    monkeypatch.setattr(endpoints.settings.app_runtime, "enabled", True)
    app = FastAPI()
    app.include_router(endpoints.router, prefix="/api/v1")
    app.dependency_overrides[desktop_principal] = lambda: principal
    app.dependency_overrides[endpoints.app_service] = lambda: service
    return TestClient(app)


# ---------------------------------------------------------------- catalog


async def test_catalog_lists_same_tenant_online_apps_visible_to_the_actor(service, principal):
    service.repository.page.return_value = (
        [
            _app(),
            _app(id="c" * 32, state="stopped"),
            _app(id="d" * 32, state="draft"),
            _app(id="e" * 32, tenant_id=1),
        ],
        None,
    )
    page = await service.page(principal)
    assert [item["id"] for item in page["items"]] == [APP_ID]
    module.check_action.assert_awaited_once()
    assert module.check_action.await_args.kwargs == {"resource_type": "app", "resource_id": APP_ID, "action": "use"}


async def test_catalog_hides_apps_the_actor_cannot_see(service, principal):
    module.check_action.return_value = False
    assert (await service.page(principal))["items"] == []


def test_catalog_keeps_the_1_3_0_shape_and_adds_runtime_enabled(client):
    response = client.get("/api/v1/dsh/apps")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["runtime_enabled"] is True
    assert data["next_cursor"] is None
    assert data["items"] == [
        {
            "id": APP_ID,
            "name": "Shared tasks",
            "slug": "shared-tasks",
            "description": "",
            "state": "online",
            "version_id": "b" * 32,
            "entry_path": "/apps/shared-tasks/",
        }
    ]


def test_catalog_is_empty_when_the_runtime_layer_is_off(client, service, monkeypatch):
    monkeypatch.setattr(endpoints.settings.app_runtime, "enabled", False)
    data = client.get("/api/v1/dsh/apps").json()["data"]
    assert data == {"items": [], "next_cursor": None, "runtime_enabled": False}
    service.repository.page.assert_not_called()
    service.runtime.sessions.validate.assert_awaited_once()


# ---------------------------------------------------------------- retired capabilities

RETIRED = [
    ("get", "/api/v1/dsh/apps?managed=true"),
    ("post", f"/api/v1/dsh/apps/{APP_ID}/launch"),
    ("get", "/api/v1/dsh/apps/deploy-limits"),
    ("post", "/api/v1/dsh/apps/deploy"),
    ("get", f"/api/v1/dsh/apps/{APP_ID}/deployments/{'d' * 32}"),
    ("get", f"/api/v1/dsh/apps/{APP_ID}/versions/{'b' * 32}/source"),
]


@pytest.mark.parametrize(("method", "path"), RETIRED)
def test_retired_desktop_capabilities_ask_for_an_upgrade(client, method, path):
    response = getattr(client, method)(path)
    assert response.status_code == 400
    body = response.json()
    assert body["status_code"] == AppDesktopClientUpgradeRequiredError.Code == 16149
    # 1.3.0 shows this string verbatim.
    assert "1.3.1" in body["status_message"]
    assert response.headers["Cache-Control"] == "no-store"


def test_retired_deploy_does_not_read_the_package(client, service):
    response = client.post(
        "/api/v1/dsh/apps/deploy",
        files={"package": ("app.tgz", b"x" * 1024)},
        data={"app_id": APP_ID, "base_version_id": "b" * 32},
    )
    assert response.json()["status_code"] == 16149
    service.repository.page.assert_not_called()


@pytest.mark.parametrize(("method", "path"), RETIRED)
def test_retired_routes_still_require_a_desktop_session(client, method, path):
    def refuse():
        raise DshInvalidAccessTokenError()

    client.app.dependency_overrides[desktop_principal] = refuse
    response = getattr(client, method)(path)
    assert response.json()["error"]["code"] == "invalid_access_token"
