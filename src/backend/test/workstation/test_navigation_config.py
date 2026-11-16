"""AC-42: navigation is tenant-inherited metadata, independent of execution."""

import json
from unittest.mock import AsyncMock

import pytest

from bisheng.core.context.tenant import get_current_tenant_id, tenant_execution_scope
from bisheng.workstation.domain.services.workstation_service import WorkStationService


@pytest.mark.parametrize("inherited", [False, True])
async def test_navigation_does_not_resolve_invalid_runtime_references(monkeypatch, inherited):
    raw = {
        "assistantIcon": {"enabled": True, "image": "tenant-icon"},
        "models": [{"id": "invalid-model"}],
        "tools": [{"id": "invalid-tool"}],
        "orgKbs": [{"id": "invalid-library"}],
    }
    resolver = AsyncMock(return_value=(json.dumps(raw), inherited, 1 if inherited else 60, not inherited))
    monkeypatch.setattr(WorkStationService, "_aresolve_tenant_config", resolver)
    runtime_config = AsyncMock(side_effect=AssertionError("navigation must not resolve runtime config"))
    monkeypatch.setattr(WorkStationService, "get_daily_chat_config", runtime_config)
    with tenant_execution_scope(60):
        result = await WorkStationService.get_navigation_config()
        assert get_current_tenant_id() == 60
    assert result["assistantIcon"]["image"] == "tenant-icon"
    assert set(result) == {"assistantIcon"}
    runtime_config.assert_not_awaited()


async def test_navigation_empty_legacy_config_does_not_seed_defaults(monkeypatch):
    monkeypatch.setattr(WorkStationService, "_aresolve_tenant_config", AsyncMock(return_value=(None, False, 1, False)))
    seed = AsyncMock(side_effect=AssertionError("read must not seed runtime defaults"))
    monkeypatch.setattr(WorkStationService, "_abuild_default_daily_config", seed)
    assert await WorkStationService.get_navigation_config() == {"assistantIcon": None}
    seed.assert_not_awaited()


async def test_navigation_http_response_does_not_enter_runtime_config(monkeypatch):
    """AC-42: the actual route returns a metadata envelope independently."""
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.workstation.api.endpoints.config import router

    monkeypatch.setattr(WorkStationService, "_aresolve_tenant_config", AsyncMock(return_value=(None, False, 60, False)))
    runtime = AsyncMock(side_effect=AssertionError("runtime config must remain outside navigation"))
    monkeypatch.setattr(WorkStationService, "get_daily_chat_config", runtime)
    app = FastAPI()
    app.dependency_overrides[UserPayload.get_login_user] = lambda: object()
    app.include_router(router, prefix="/api/v1/workstation")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/workstation/config", params={"purpose": "navigation"})
    assert response.status_code == 200
    assert response.json()["status_code"] == 200
    assert response.json()["data"] == {"assistantIcon": None}
    runtime.assert_not_awaited()
