from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from starlette.testclient import TestClient

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import PageData
from bisheng.developer_token.domain.schemas import (
    DeveloperTokenCreateResponse,
    DeveloperTokenGlobalConfig,
    DeveloperTokenRead,
    DeveloperTokenSecretResponse,
)

ENDPOINT_MOD = "bisheng.developer_token.api.endpoints.developer_token"


def _user():
    u = MagicMock(spec=UserPayload)
    u.user_id = 1
    u.tenant_id = 1
    return u


def _app(login_user):
    from bisheng.admin.api.router import router as admin_router

    app = FastAPI()
    app.include_router(admin_router, prefix="/api/v1")
    app.dependency_overrides[UserPayload.get_login_user] = lambda: login_user
    return app


def _read():
    return DeveloperTokenRead(
        id=1,
        tenant_id=1,
        user_id=1,
        name="api",
        token_prefix="bst_abc",
        enabled=True,
        override_ip_whitelist=False,
        override_rate_limit=False,
    )


def test_list_tokens_omits_plaintext_secret():
    app = _app(_user())
    client = TestClient(app)
    with patch(
        f"{ENDPOINT_MOD}.DeveloperTokenService.list_tokens",
        new=AsyncMock(return_value=PageData(data=[_read()], total=1)),
    ):
        resp = client.get("/api/v1/admin/developer-tokens")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 1
    assert "plaintext_token" not in data["data"][0]


def test_create_token_returns_plaintext_once():
    app = _app(_user())
    client = TestClient(app)
    service_mock = AsyncMock(return_value=DeveloperTokenCreateResponse(token=_read(), plaintext_token="bst_secret"))
    with patch(
        f"{ENDPOINT_MOD}.DeveloperTokenService.create_token",
        new=service_mock,
    ):
        resp = client.post(
            "/api/v1/admin/developer-tokens",
            json={"name": "api", "user_id": 1, "department_id": 20},
        )

    assert resp.status_code == 200
    assert resp.json()["data"]["plaintext_token"] == "bst_secret"
    payload = service_mock.await_args.args[1]
    assert payload.user_id == 1
    assert payload.department_id == 20
    assert not hasattr(payload, "tenant_id")


def test_update_token_does_not_rotate_secret():
    app = _app(_user())
    client = TestClient(app)
    with patch(
        f"{ENDPOINT_MOD}.DeveloperTokenService.update_token",
        new=AsyncMock(return_value=_read()),
    ):
        resp = client.put("/api/v1/admin/developer-tokens/1", json={"name": "renamed"})

    assert resp.status_code == 200
    assert "plaintext_token" not in resp.json()["data"]


def test_secret_view_route_returns_secret_payload():
    app = _app(_user())
    client = TestClient(app)
    with patch(
        f"{ENDPOINT_MOD}.DeveloperTokenService.view_secret",
        new=AsyncMock(
            return_value=DeveloperTokenSecretResponse(
                id=1,
                token_prefix="bst_abc",
                plaintext_token="bst_secret",
            )
        ),
    ):
        resp = client.get("/api/v1/admin/developer-tokens/1/secret")

    assert resp.status_code == 200
    assert resp.json()["data"]["plaintext_token"] == "bst_secret"


def test_global_config_routes():
    app = _app(_user())
    client = TestClient(app)
    with patch(
        f"{ENDPOINT_MOD}.DeveloperTokenService.get_global_config",
        new=AsyncMock(return_value=DeveloperTokenGlobalConfig()),
    ):
        resp = client.get("/api/v1/admin/developer-tokens/config/global")
    assert resp.status_code == 200

    with patch(
        f"{ENDPOINT_MOD}.DeveloperTokenService.update_global_config",
        new=AsyncMock(return_value=DeveloperTokenGlobalConfig(ip_whitelist="10.0.0.1", rate_limit_per_minute=1)),
    ):
        resp = client.put(
            "/api/v1/admin/developer-tokens/config/global",
            json={"ip_whitelist": "10.0.0.1", "rate_limit_per_minute": 1},
        )
    assert resp.status_code == 200
    assert resp.json()["data"]["rate_limit_per_minute"] == 1
