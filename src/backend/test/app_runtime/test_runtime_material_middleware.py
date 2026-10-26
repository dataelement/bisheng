"""覆盖 AC: AC-15、AC-47、AC-48. Material keys own identity under multi-tenancy."""

import httpx
import pytest
from fastapi import FastAPI, Request

from bisheng.utils import http_middleware as middleware
from test.app_runtime.test_runtime_material_service import P


@pytest.mark.parametrize("path", [P + "/exchange", P + "/transfers/11111111-1111-4111-8111-111111111111/content"])
def test_material_channel_is_tenant_exempt_and_does_not_decode_browser_credentials(path):
    assert path.startswith(middleware.TENANT_CHECK_EXEMPT_PATHS)
    assert not middleware._uses_browser_identity(path)
    assert middleware._uses_browser_identity("/api/v1/apps")
    assert not (P + "-foreign/exchange").startswith(middleware.TENANT_CHECK_EXEMPT_PATHS)


async def test_stale_browser_cookie_cannot_select_material_request_identity(monkeypatch):
    from bisheng.core.context import tenant

    def no_decode(_):
        pytest.fail("Material channel must not decode browser credentials")

    monkeypatch.setattr(middleware, "_decode_jwt_subject", no_decode)
    monkeypatch.setattr(middleware, "_set_tenant_context", lambda *args, **kwargs: None)
    app = FastAPI()
    app.add_middleware(middleware.CustomMiddleware)

    @app.get(P + "/exchange")
    async def echo(request: Request):
        return {"bypass": tenant.is_tenant_filter_bypassed()}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(P + "/exchange", headers={"cookie": "access_token_cookie=expired-browser-token"})
    assert response.status_code == 200 and response.json()["bypass"] is True
