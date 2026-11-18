from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from bisheng.admin.application import request_admission
from bisheng.admin.application.tenant_scope import EffectiveManagementScope
from bisheng.common import permission_identity
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.request_scope import RequestScope, endpoint_scope
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.dsh_market import infrastructure
from bisheng.dsh_market.api.endpoints import router
from bisheng.dsh_market.infrastructure import get_market_service, get_workbench_service


async def test_market_management_lists_use_admitted_tenant_and_remove_operation_fields(monkeypatch):
    login = SimpleNamespace(user_id=10, tenant_id=1, is_global_super=True)
    selected = AsyncMock(return_value=EffectiveManagementScope(7, "selected", None))
    monkeypatch.setattr(request_admission, "authenticate_browser", AsyncMock(return_value=login))
    monkeypatch.setattr(request_admission, "request_target", selected)
    monkeypatch.setattr(infrastructure, "tenant_is_active", AsyncMock(return_value=True))
    admin = AsyncMock(return_value=True)
    monkeypatch.setattr(permission_identity, "check_tenant_admin", admin)

    def load(tenant, *args, **kwargs):
        assert get_current_tenant_id() == tenant
        return {
            "total": tenant,
            "data": [
                {
                    "id": "one",
                    "tenant_id": tenant,
                    "revision": 3,
                    "display_name": f"tenant-{tenant}",
                    "description": "",
                    "updated_at": "2026-11-18",
                    "current_version_id": "v",
                    "versions": [
                        {
                            "id": "v",
                            "version": "1.0.0",
                            "manifest": {
                                "targets": {"mac": {"private": "digest"}},
                                "plugin": {"services": ["internal"]},
                            },
                        }
                    ],
                    "current_version": {"id": "v", "version": "1.0.0", "artifact_url": "/download"},
                    "workbench_key": "sample",
                    "legacy_id": None,
                    "screenshots": [{"url": "/download"}],
                }
            ],
        }

    loader = Mock(side_effect=load)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_market_service] = lambda: SimpleNamespace(list_plugins=loader)
    app.dependency_overrides[get_workbench_service] = lambda: SimpleNamespace(list=loader)
    app.add_exception_handler(BaseErrorCode, lambda req, exc: JSONResponse(exc.return_resp_instance().model_dump()))
    paths = ["/api/v1/dsh/market/admin/plugins", "/api/v1/dsh/market/admin/workbenches"]
    for route in app.routes:
        if route.path in paths:
            kind = endpoint_scope(route.endpoint)
            assert kind == RequestScope.TENANT
            route.app = request_admission.ScopedEndpoint(route.app, kind)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://asgi") as client:
        for path in paths:
            response = await client.get(path, headers={"X-Management-Tenant": "7", "X-DSH-Market-Tenant": "1"})
            assert response.headers["X-Management-Tenant"] == "7"
            data = response.json()["data"]
            assert data["total"] == 7 and data["read_only"] is True
            assert data["data"][0]["display_name"] == "tenant-7"
            assert "revision" not in data["data"][0]
            assert not any(x in str(data) for x in ("artifact_url", "screenshots", "services", "digest"))
        selected.return_value = EffectiveManagementScope(1, "selected", None)
        assert (await client.get(paths[0], headers={"X-Management-Tenant": "7"})).status_code == 409
        own = (await client.get(paths[0], headers={"X-Management-Tenant": "1"})).json()["data"]
        assert own["total"] == 1 and own["data"][0]["revision"] == 3
        login.is_global_super = False
        assert (await client.get(paths[1], headers={"X-Management-Tenant": "7"})).status_code == 409
        assert (await client.get(paths[1], headers={"X-Management-Tenant": "1"})).json()["data"]["total"] == 1
        admin.return_value = False
        assert (await client.get(paths[0])).json()["status_code"] == 26204
        login._dsh_web_session_tenant_id = 7
        desktop = await client.get(paths[1], headers={"X-Management-Tenant": "7"})
        assert desktop.json()["status_code"] == 26204
