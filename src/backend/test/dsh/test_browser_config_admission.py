"""Login discovery must remain public through the production route admission layer."""

from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from bisheng.admin.application import request_admission
from bisheng.dsh.api.dependencies import get_settings
from bisheng.dsh.api.endpoints.settings import settings_service
from bisheng.dsh.api.router import router
from bisheng.dsh.config import DshSettings
from bisheng.dsh.domain.schemas.settings import DshManagementSettings


@pytest.mark.parametrize("billing_enabled", [True, False])
async def test_anonymous_login_config_bypasses_auth_but_admin_settings_do_not(monkeypatch, billing_enabled):
    from bisheng.common.services.config_service import settings

    monkeypatch.setattr(settings.credit_billing, "enabled", billing_enabled)
    authenticate = AsyncMock(side_effect=HTTPException(status_code=401, detail="Authentication required"))
    monkeypatch.setattr(request_admission, "authenticate_browser", authenticate)
    service = AsyncMock()
    service.read.return_value = DshManagementSettings(
        enabled=True, download_url="https://desktop.example/download", launch_url="bisheng://login"
    )
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_settings] = lambda: DshSettings(
        platform_public_url="http://test", gateway_internal_url="http://gateway"
    )
    app.dependency_overrides[settings_service] = lambda: service
    request_admission.install_request_admission(app)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/dsh/browser-config")
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
        expected = service.read.return_value
        assert response.json()["data"] == {
            **expected.model_dump(),
            "management_enabled": True,
            "credit_billing_enabled": billing_enabled,
        }
        authenticate.assert_not_awaited()

        for method in ("GET", "PUT"):
            denied = await client.request(method, "/api/v1/dsh/admin/settings", json={"enabled": True})
            assert denied.status_code == 401
        assert authenticate.await_count == 2
        service.save.assert_not_awaited()

    service.read.assert_awaited_once_with()
