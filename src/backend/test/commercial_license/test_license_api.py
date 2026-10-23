from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from starlette.testclient import TestClient

from bisheng.common.dependencies.core_deps import get_db_session
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.main import handle_http_exception

ENDPOINT_MOD = "bisheng.commercial_license.api.router"


def _mk_user(*, is_global_super: bool):
    user = MagicMock(spec=UserPayload)
    user.user_id = 1
    user.is_global_super = is_global_super
    return user


def _build_app(login_user):
    from bisheng.commercial_license.api.router import router

    app = FastAPI()
    app.add_exception_handler(BaseErrorCode, handle_http_exception)
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[UserPayload.get_login_user] = lambda: login_user
    app.dependency_overrides[get_db_session] = lambda: MagicMock()
    return app


def test_super_admin_get_status_returns_four_states_only():
    now = datetime(2026, 9, 14, 10, 0, 0)
    payload = {
        "licenses": [
            {
                "license_code": "etl",
                "license_name": "etl",
                "display_state": "expiring",
                "expire_date": "2026-09-30",
                "days_remaining": 16,
                "checked_at": now.isoformat(),
            }
        ],
        "checked_at": now.isoformat(),
    }
    with (
        patch(f"{ENDPOINT_MOD}.LicenseInfoRepository"),
        patch(f"{ENDPOINT_MOD}.list_license_status", new_callable=AsyncMock, return_value=payload),
    ):
        client = TestClient(_build_app(_mk_user(is_global_super=True)))
        response = client.get("/api/v1/commercial-licenses/status")
    assert response.status_code == 200
    body = response.json()
    assert body["status_code"] == 200
    licenses = body["data"]["licenses"]
    assert licenses[0]["display_state"] in {"normal", "expiring", "expired", "unknown"}
    assert set(licenses[0]) == {
        "license_code",
        "license_name",
        "display_state",
        "expire_date",
        "days_remaining",
        "checked_at",
    }


def test_non_super_get_returns_empty_200():
    with patch(f"{ENDPOINT_MOD}.LicenseInfoRepository") as repo_cls:
        client = TestClient(_build_app(_mk_user(is_global_super=False)))
        response = client.get("/api/v1/commercial-licenses/status")
    assert response.status_code == 200
    assert response.json()["data"]["licenses"] == []
    repo_cls.assert_not_called()


def test_empty_table_super_get_returns_empty_without_dashboard_http():
    payload = {"licenses": [], "checked_at": datetime.now().isoformat()}
    dashboard_http = AsyncMock()
    with (
        patch(f"{ENDPOINT_MOD}.LicenseInfoRepository"),
        patch(f"{ENDPOINT_MOD}.list_license_status", new_callable=AsyncMock, return_value=payload) as list_status,
    ):
        client = TestClient(_build_app(_mk_user(is_global_super=True)))
        response = client.get("/api/v1/commercial-licenses/status")
    assert response.status_code == 200
    assert response.json()["data"]["licenses"] == []
    list_status.assert_awaited_once()
    dashboard_http.assert_not_awaited()


def test_super_post_gateway_upserts():
    with (
        patch(f"{ENDPOINT_MOD}.LicenseInfoRepository"),
        patch(f"{ENDPOINT_MOD}.upsert_mapped", new_callable=AsyncMock) as upsert,
    ):
        client = TestClient(_build_app(_mk_user(is_global_super=True)))
        response = client.post(
            "/api/v1/commercial-licenses/gateway",
            json={
                "version": "trial",
                "expire_day": "2026-07-02",
                "days_remaining": -74,
                "severity": "expired",
                "expired": True,
            },
        )
    assert response.status_code == 200
    assert response.json()["status_code"] == 200
    upsert.assert_awaited_once()
    assert upsert.await_args.args[1]["license_code"] == "gateway"


def test_invalid_gateway_body_returns_27001():
    with patch(f"{ENDPOINT_MOD}.LicenseInfoRepository"):
        client = TestClient(_build_app(_mk_user(is_global_super=True)))
        response = client.post("/api/v1/commercial-licenses/gateway", json={})
    assert response.status_code == 200
    assert response.json()["status_code"] == 27001


def test_unauthenticated_uses_existing_auth():
    from bisheng.commercial_license.api.router import router

    app = FastAPI()
    app.add_exception_handler(BaseErrorCode, handle_http_exception)

    async def _reject():
        raise UnAuthorizedError()

    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[UserPayload.get_login_user] = _reject
    app.dependency_overrides[get_db_session] = lambda: MagicMock()
    client = TestClient(app)
    response = client.get("/api/v1/commercial-licenses/status")
    assert response.json()["status_code"] == 403
