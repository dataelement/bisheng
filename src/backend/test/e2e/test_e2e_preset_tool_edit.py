"""Preset edit HTTP -> service -> business adapter -> action runtime -> SQL.

Uses isolated SQLite and an injected FGA transport; login identity is injected.
This is local API-chain coverage, not acceptance against a deployed FGA store.
"""

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode import BaseErrorCode
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.permission.application import business_authorization
from bisheng.permission.application.resource_authorization import ResourceAuthorizationRegistry
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from bisheng.tool.api.tool import router
from bisheng.tool.domain.models import gpts_tools
from bisheng.tool.domain.models.gpts_tools import GptsTools, GptsToolsType
from bisheng.tool.domain.repositories import creation_repository
from bisheng.tool.domain.services.f048_tool_permission import F048ToolPermissionAdapter, ToolDaoPermissionLoader
from bisheng.tool.domain.services.tool import ToolResourceAuthorizationPort
from test.e2e.helpers.api import assert_resp_200, assert_resp_error
from test.permission.test_f048_permission_service import _service


@pytest.fixture
async def api(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    # The existing list ordering uses MySQL FIELD; emulate it in the SQLite fixture.
    @event.listens_for(engine.sync_engine, "connect")
    def sqlite_field(connection, _record):
        connection.create_function(
            "field", -1, lambda value, *values: values.index(value) + 1 if value in values else 0
        )

    async with engine.begin() as conn:
        for model in (GptsToolsType, GptsTools):
            await conn.run_sync(model.__table__.create)

    @asynccontextmanager
    async def session():
        async with AsyncSession(engine, expire_on_commit=False) as db:
            yield db

    monkeypatch.setattr(gpts_tools, "get_async_db_session", session)
    monkeypatch.setattr(creation_repository, "get_async_db_session", session)
    async with session() as db:
        for resource_id, tenant_id in ((201, 68), (202, 69)):
            db.add(
                GptsToolsType(
                    id=resource_id,
                    name=f"e2e-preset-edit-{resource_id}",
                    tenant_id=tenant_id,
                    is_preset=1,
                    extra=json.dumps({"api_key": "synthetic-secret", "endpoint": "old"}),
                )
            )
            db.add(
                GptsTools(
                    id=resource_id,
                    type=resource_id,
                    name="e2e-preset-edit-tool",
                    tool_key="tianyancha",
                    tenant_id=tenant_id,
                    is_preset=1,
                )
            )
        await db.commit()

    runtime, catalog, _, _, fga, _, _ = _service()
    catalog.available.add(("tool", "edit"))
    fga.allowed = True

    async def batch_check(checks, consistency=None):
        return [row["relation"] == "visible" or fga.allowed for row in checks]

    fga.batch_check = batch_check
    versions = type("Versions", (), {"get_permission_version": AsyncMock(return_value=(1, "test"))})()
    adapter = F048ToolPermissionAdapter(loader=ToolDaoPermissionLoader(versions), permission=runtime)
    registry = ResourceAuthorizationRegistry()
    registry.register("tool", ToolResourceAuthorizationPort(adapter))
    monkeypatch.setattr(business_authorization, "get_f048_resource_registry", AsyncMock(return_value=registry))
    monkeypatch.setattr(business_authorization, "get_f048_runtime", AsyncMock(return_value=runtime))
    monkeypatch.setattr(
        business_authorization,
        "resolve_permission_actor",
        AsyncMock(return_value=PermissionActor(user_id=42, current_tenant_id=68)),
    )
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[UserPayload.get_login_user] = lambda: UserPayload(user_id=42, tenant_id=68, user_role=[])

    @app.exception_handler(BaseErrorCode)
    async def handle_error(request, exc):
        return JSONResponse(status_code=200, content=exc.to_dict())

    try:
        with tenant_execution_scope(68):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                yield client, fga
    finally:
        await engine.dispose()


async def test_edit_grant_save_read_and_revoke(api):
    """AC-01/02/05: exact edit permission permits saving; revoke blocks writes."""
    client, fga = api
    assert (
        assert_resp_200(
            await client.post(
                "/api/v1/tool/config", json={"tool_id": 201, "extra": {"api_key": "********", "endpoint": "updated"}}
            )
        )
        is True
    )
    assert ("user:42", "can_edit", "tool:201", None) in fga.checks
    result = assert_resp_200(await client.get("/api/v1/tool", params={"is_preset": 1}))
    row = next(item for item in result if item["id"] == 201)
    assert json.loads(row["extra"]) == {"api_key": "********", "endpoint": "updated"}
    assert "synthetic-secret" not in json.dumps(result)
    fga.allowed = False
    assert_resp_error(
        await client.post("/api/v1/tool/config", json={"tool_id": 201, "extra": {"endpoint": "forbidden"}}), 403
    )
    row = await gpts_tools.GptsToolsDao.aget_one_tool_type(201)
    assert json.loads(row.extra) == {"api_key": "synthetic-secret", "endpoint": "updated"}


async def test_foreign_preset_denied_before_action_check(api):
    """AC-04: even an allowed action cannot edit another tenant's preset."""
    client, fga = api
    assert_resp_error(
        await client.post("/api/v1/tool/config", json={"tool_id": 202, "extra": {"endpoint": "forbidden"}}), 403
    )
    assert not fga.checks
