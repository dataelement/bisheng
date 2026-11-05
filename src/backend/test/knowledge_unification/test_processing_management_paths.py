"""T265: alternate integer URLs must retain the browser tenant pin.

Coverage: AC-04, AC-05, AC-35, AC-66, AC-84.
The ASGI app exercises the real middleware and FastAPI's integer parsing;
resource authorization remains the responsibility of the later Owner endpoint.
"""

import httpx
import pytest
from fastapi import FastAPI

from bisheng.admin.application import tenant_scope
from bisheng.admin.application.tenant_scope import EffectiveManagementScope
from bisheng.common.middleware import admin_scope


@pytest.mark.parametrize("space_segment", ["%2B7", "%207%20"])
@pytest.mark.parametrize(
    ("method", "suffix"),
    [
        ("PUT", "processing-settings"),
        ("POST", "processing-jobs"),
        ("POST", "processing-jobs/precheck"),
        ("POST", "processing-jobs/job-id/retry"),
    ],
)
async def test_equivalent_integer_paths_require_expected_tenant(monkeypatch, space_segment, method, suffix):
    async def not_global_super(_user_id):
        return False

    async def resolve_scope(_user_id, **_kwargs):
        return EffectiveManagementScope(tenant_id=101, source="default", expires_at=None)

    monkeypatch.setattr(admin_scope, "_extract_http_access_token", lambda _request: "test-only")
    monkeypatch.setattr(admin_scope, "_decode_jwt_subject", lambda _token: {"user_id": 11})
    monkeypatch.setattr(admin_scope, "_check_is_global_super", not_global_super)
    monkeypatch.setattr(tenant_scope, "resolve_management_scope", resolve_scope)

    app = FastAPI()
    app.add_middleware(admin_scope.AdminScopeMiddleware)

    async def accepted(space_id: int):
        return {"space_id": space_id}

    app.add_api_route("/api/v1/knowledge/space/{space_id}/" + suffix, accepted, methods=[method])
    path = "/api/v1/knowledge/space/" + space_segment + "/" + suffix
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        missing = await client.request(method, path)
        assert missing.status_code == 400
        mismatched = await client.request(method, path, headers={"X-Management-Tenant": "202"})
        assert mismatched.status_code == 409
        matching = await client.request(method, path, headers={"X-Management-Tenant": "101"})
        assert matching.status_code == 200
        assert matching.json() == {"space_id": 7}
