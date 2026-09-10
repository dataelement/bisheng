"""Browser self-service scope, CSRF, disabled gate and display-only department coverage."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlmodel import Session

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.dsh import DshDshDisabledError, DshUserDisabledError
from bisheng.dsh.api.dependencies import get_runtime
from bisheng.dsh.api.endpoints import self_service as api
from bisheng.dsh.domain.repositories.identities import CurrentIdentityRecords
from bisheng.dsh.domain.services.self_service import DshSelfService
from test.dsh.test_policy_repository import sql_store  # noqa: F401
from test.dsh.test_profile_outbox import user_store  # noqa: F401

USER = SimpleNamespace(user_id=20, tenant_id=2)


def runtime():
    return SimpleNamespace(
        settings=SimpleNamespace(platform_public_url="http://test"), gateway=SimpleNamespace(request=AsyncMock())
    )


async def test_browser_identity_cannot_select_another_subject(monkeypatch):
    rt = runtime()
    identity = AsyncMock(return_value=SimpleNamespace(active=True, tenant_active=True, natural_person=True))
    monkeypatch.setattr(CurrentIdentityRecords, "get", identity)
    rt.gateway.request.return_value = {"items": [], "next_cursor": None, "has_more": False}
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1")
    app.dependency_overrides[UserPayload.get_login_user] = lambda: USER
    app.dependency_overrides[get_runtime] = lambda: rt
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/dsh/me/sessions?user_id=99&tenant_id=3")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["data"]["items"] == []
        identity.assert_awaited_with("2", "20")
        assert rt.gateway.request.await_args.args[1]["user_id"] == "20"
        assert rt.gateway.request.await_args.args[1]["tenant_id"] == "2"
        assert (await client.get("/api/v1/dsh/me/sessions?limit=101")).status_code == 400
        session_id = str(uuid4())
        rt.gateway.request.reset_mock()
        for origin in (None, "http://evil"):
            headers = {"origin": origin} if origin else {}
            assert (
                await client.post(f"/api/v1/dsh/me/sessions/{session_id}/revoke", headers=headers, json={})
            ).status_code == 403
        rt.gateway.request.assert_not_awaited()
        rt.gateway.request.return_value = {"session_id": session_id, "state": "REVOKED"}
        response = await client.post(
            f"/api/v1/dsh/me/sessions/{session_id}/revoke", headers={"origin": "http://test"}, json={"user_id": 99}
        )
        assert response.status_code == 200
        assert rt.gateway.request.await_args.args == (
            "self_revoke",
            {"tenant_id": "2", "user_id": "20", "session_id": session_id},
        )

        async def disabled():
            raise DshDshDisabledError()

        app.dependency_overrides[get_runtime] = disabled
        assert (await client.get("/api/v1/dsh/me/sessions")).status_code == 403

        async def anonymous():
            raise HTTPException(401)

        app.dependency_overrides[UserPayload.get_login_user] = anonymous
        assert (await client.get("/api/v1/dsh/me/sessions")).status_code == 401


async def test_moved_or_disabled_user_never_reaches_gateway(monkeypatch):
    rt = runtime()
    lookup = AsyncMock(return_value=None)
    monkeypatch.setattr(CurrentIdentityRecords, "get", lookup)
    service = DshSelfService(rt)
    for result in (
        None,
        SimpleNamespace(active=False, tenant_active=True, natural_person=True),
        SimpleNamespace(active=True, tenant_active=False, natural_person=True),
    ):
        lookup.return_value = result
        with pytest.raises(DshUserDisabledError):
            await service.sessions(USER)
        with pytest.raises(DshUserDisabledError):
            await service.revoke(USER, str(uuid4()))
    rt.gateway.request.assert_not_awaited()


def test_primary_department_is_display_only_and_missing_is_null(user_store):  # noqa: F811
    from bisheng.database.models.department import Department, UserDepartment
    from bisheng.user.domain.repositories.dsh_display import DshDisplayRepository
    from bisheng.user.domain.repositories.dsh_profile import UserDshProfileRepository

    with Session(user_store) as session:
        assert DshDisplayRepository.read(session, [20])[20]["department_name"] is None
        session.add(Department(id=1, dept_id="test-dept", name="Engineering", tenant_id=2))
        session.add(Department(id=2, dept_id="other-dept", name="Secondary", tenant_id=2))
        session.add(UserDepartment(id=1, user_id=20, department_id=1, is_primary=1))
        session.add(UserDepartment(id=2, user_id=20, department_id=2, is_primary=0))
        session.commit()
        assert DshDisplayRepository.read(session, [20])[20]["department_name"] == "Engineering"
        assert "department_name" not in UserDshProfileRepository.batch_snapshot(session, [20])[20]
        assert DshDisplayRepository.read(session, []) == {}


async def test_usage_exposes_only_authorized_models_without_a_seat(monkeypatch):
    from bisheng.core.context.tenant import get_current_tenant_id
    from bisheng.dsh import admin_runtime
    from bisheng.dsh import runtime as model_runtime

    rt = runtime()
    rt.settings.billing_timezone = "Asia/Shanghai"
    service = DshSelfService(rt)
    monkeypatch.setattr(service, "identity", AsyncMock())
    policy = SimpleNamespace(
        monthly_token_limit=100,
        version=1,
        quota_sync_state="READY",
        model_configs=[SimpleNamespace(model_id=4, monthly_token_limit=100, model_dump=lambda: {})],
    )
    monkeypatch.setattr(model_runtime, "read_policy", AsyncMock(return_value=policy))

    async def available(ids, loader):
        assert ids == [4]
        assert get_current_tenant_id() == 2
        return [{"id": 4, "name": "Provider / Model", "is_root_shared": False}]

    monkeypatch.setattr(admin_runtime, "read_available_models", available)
    monkeypatch.setattr(admin_runtime, "read_unknown_pending", AsyncMock(return_value=1))
    model = SimpleNamespace(
        prepare_month=AsyncMock(
            return_value={
                "models": {"4": 10, "999": 50},
                "model_limits": {"4": 100},
                "used": 60,
                "limit": 100,
                "remaining": 40,
                "source": "live",
                "quota_state": "ready",
                "as_of": "2026-09-10T00:00:00Z",
            }
        )
    )
    monkeypatch.setattr(model_runtime, "get_model_runtime", AsyncMock(return_value=model))
    result = await service.usage(USER)
    assert result["models"] == [{"model_id": 4, "name": "Provider / Model", "limit": 100, "used": 10, "remaining": 90}]
    assert result["billing_timezone"] == "Asia/Shanghai"
    rt.gateway.request.assert_not_awaited()
