"""覆盖 AC: AC-09, AC-11, AC-25, AC-26, AC-27, AC-28, AC-29, AC-30, AC-33."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from bisheng.dsh.domain.schemas.model_policy import DshModelQuotaConfig


async def test_eight_routes_use_verified_actor_and_reject_body_spoofing():
    from bisheng.dsh.api.endpoints import admin

    app = FastAPI()
    app.include_router(admin.router, prefix="/api/v1")
    service = SimpleNamespace(
        **{
            name: AsyncMock(return_value={"status": "PROCESSING"})
            for name in ("users", "license", "update_policy", "command", "operation", "get_policy", "sessions")
        }
    )
    app.dependency_overrides[admin.admin_user] = lambda: SimpleNamespace(user_id=90)
    app.dependency_overrides[admin.get_management] = lambda: service
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        routes = [
            ("GET", "/users", None),
            ("GET", "/license", None),
            (
                "PUT",
                "/users/20/models/4/policy",
                {
                    "operation_id": "00000000-0000-4000-8000-000000000001",
                    "expected_version": 0,
                    "enabled": False,
                    "monthly_token_limit": 0,
                },
            ),
            (
                "POST",
                "/users/20/revoke",
                {"operation_id": "00000000-0000-4000-8000-000000000001", "expected_grant_version": 1},
            ),
            (
                "POST",
                "/users/20/reassign",
                {"operation_id": "00000000-0000-4000-8000-000000000001", "expected_grant_version": 1},
            ),
            ("GET", "/operations/op", None),
            ("GET", "/users/20/policy", None),
            ("GET", "/users/20/sessions", None),
        ]
        for method, path, body in routes:
            response = await client.request(method, "/api/v1/dsh/admin" + path, json=body)
            assert response.status_code == 200
            assert response.json()["data"]["status"] == "PROCESSING"
        assert service.command.await_args_list[0].args[0] == 90
        response = await client.post(
            "/api/v1/dsh/admin/users/20/revoke",
            json={"operation_id": "x", "expected_grant_version": 1, "actor_user_id": 1},
        )
        assert response.status_code in (400, 422)
        response = await client.post(
            "/api/v1/dsh/admin/users/20/revoke", json={"operation_id": "not-uuid", "expected_grant_version": 1}
        )
        assert response.status_code in (400, 422)
        response = await client.get("/api/v1/dsh/admin/users?limit=101")
        assert response.status_code in (400, 422)


@pytest.mark.parametrize(
    "scope,requested,allowed,instance", [(2, 3, False, False), (2, 2, True, False), (None, None, True, True)]
)
async def test_production_authorizer_honors_scope(monkeypatch, scope, requested, allowed, instance):
    from fastapi import HTTPException

    from bisheng.core.context import tenant
    from bisheng.database.models.tenant import UserTenantDao
    from bisheng.dsh.admin_runtime import authorize_admin
    from bisheng.permission import application
    from bisheng.user.domain.models.user import UserDao
    from bisheng.user.domain.models.user_role import UserRoleDao

    permissions = SimpleNamespace(check=AsyncMock(return_value=instance))
    monkeypatch.setattr(application, "get_permission_relation_api", AsyncMock(return_value=permissions))
    monkeypatch.setattr(application, "is_tenant_admin", AsyncMock(return_value=True))
    monkeypatch.setattr(UserDao, "aget_user", AsyncMock(return_value=SimpleNamespace(delete=0)))
    monkeypatch.setattr(UserTenantDao, "aget_active_user_tenant", AsyncMock(return_value=SimpleNamespace(tenant_id=2)))
    monkeypatch.setattr(UserRoleDao, "aget_user_roles", AsyncMock(return_value=[]))
    token = tenant.current_tenant_id.set(scope)
    override = tenant.set_admin_scope_tenant_id(None)
    try:
        if not allowed:
            with pytest.raises(HTTPException) as error:
                await authorize_admin(90, requested)
            assert error.value.status_code == 403
        else:
            actor, target = await authorize_admin(90, requested)
            assert actor["scope"] == ("instance" if instance else "tenant")
            assert target == requested
    finally:
        override.var.reset(override)
        tenant.current_tenant_id.reset(token)


async def test_policy_view_survives_unavailable_quota_with_persisted_source(monkeypatch):
    from bisheng.core.context.tenant import current_tenant_id
    from bisheng.dsh.admin_runtime import build_policy_view

    policy = SimpleNamespace(
        version=1,
        quota_sync_state="READY",
        model_configs=[DshModelQuotaConfig(model_id=4, monthly_token_limit=100)],
        monthly_token_limit=100,
        model_dump=lambda: {"version": 1, "model_configs": [{"model_id": 4, "monthly_token_limit": 100}]},
    )
    view = build_policy_view(
        policy_reader=AsyncMock(return_value=policy),
        live_reader=AsyncMock(side_effect=TimeoutError()),
        persisted_reader=AsyncMock(
            return_value={
                "source": "sql_estimate",
                "used": 12,
                "remaining": 88,
                "limit": 100,
                "as_of": None,
                "quota_state": "unavailable",
                "models": {"4": 12},
                "model_limits": {"4": 120},
                "unknown_pending": 2,
            }
        ),
        billing_timezone="Asia/Shanghai",
    )
    token = current_tenant_id.set(2)
    try:
        result = await view(20)
        assert result["models"] == [{"model_id": 4, "monthly_token_limit": 100}]
        assert "monthly_token_limit" not in result
        assert "model_configs" not in result
        assert result["usage"]["model_limits"] == {"4": 120}
        assert result["usage"]["source"] == "persisted" and result["usage"]["quota_state"] == "unavailable"
        assert result["usage"]["models"] == {"4": 12}
        assert result["usage"]["unknown_pending"] == 2
    finally:
        current_tenant_id.reset(token)


async def test_unknown_count_remains_visible_without_a_reliable_summary():
    from bisheng.dsh.admin_runtime import build_policy_view

    policy = SimpleNamespace(
        version=1,
        quota_sync_state="READY",
        model_configs=[DshModelQuotaConfig(model_id=4, monthly_token_limit=100)],
        monthly_token_limit=100,
        model_dump=lambda: {"version": 1},
    )
    view = build_policy_view(
        policy_reader=AsyncMock(return_value=policy),
        live_reader=AsyncMock(side_effect=TimeoutError()),
        persisted_reader=AsyncMock(side_effect=ValueError("No aggregate")),
        unknown_reader=AsyncMock(return_value=2),
        billing_timezone="UTC",
    )
    result = await view(20)
    assert result["usage"]["source"] == "unavailable"
    assert result["usage"]["used"] is None and result["usage"]["remaining"] is None
    assert result["usage"]["unknown_pending"] == 2
