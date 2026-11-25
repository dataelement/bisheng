"""T049: browser request contract, tenant/actor fences and durable read-only lookup."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from bisheng.admin.application import tenant_scope
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.department import DepartmentNotFoundError
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.knowledge.api.endpoints import knowledge_space as routes
from bisheng.knowledge.application import provider_provision_runtime as runtime
from bisheng.knowledge.application.provider_provisioning import create_item_key
from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderOperation as Op
from bisheng.knowledge.domain.repositories import provider_provision_repository as repository
from bisheng.knowledge.domain.services import department_knowledge_space_service as department_service

BASE = "/api/v1/knowledge/space/department"
HEADERS = {"X-Management-Tenant": "7"}
PREVIEW = {"department_id": 20}
STATUS = {"request_key": "batch", "department_ids": [20]}


@pytest.fixture
async def browser(monkeypatch):
    user = SimpleNamespace(user_id=42, is_global_super=False, is_admin=lambda: False)
    scope = AsyncMock(return_value=tenant_scope.EffectiveManagementScope(7, "own", None))
    monkeypatch.setattr(routes, "resolve_management_scope", scope)
    monkeypatch.setattr(tenant_scope, "resolve_management_scope", scope)
    monkeypatch.setattr(department_service, "is_current_tenant_administrator", AsyncMock(return_value=True))
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1")
    app.dependency_overrides[UserPayload.get_login_user] = lambda: user

    @app.exception_handler(BaseErrorCode)
    async def domain_error(request, exc):
        return JSONResponse(exc.return_resp_instance().model_dump())

    with tenant_execution_scope(7):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://app") as client:
            yield client


@pytest.mark.parametrize("route,body", [("provider-preview", PREVIEW), ("batch-status", STATUS)])
async def test_rejects_missing_stale_or_mismatched_tenant_and_non_admin(browser, monkeypatch, route, body):
    url = f"{BASE}/{route}"
    for headers, code in [({}, 19703), ({"X-Management-Tenant": "8"}, 19704)]:
        assert (await browser.post(url, headers=headers, json=body)).json()["status_code"] == code
    with tenant_execution_scope(8):
        assert (await browser.post(url, headers=HEADERS, json=body)).json()["status_code"] == 19704
    monkeypatch.setattr(department_service, "is_current_tenant_administrator", AsyncMock(return_value=False))
    assert (await browser.post(url, headers=HEADERS, json=body)).json()[
        "status_code"
    ] == department_service.UnAuthorizedError.Code


async def test_preview_uses_department_gate_before_remote_probe(browser, monkeypatch):
    p = runtime.Preset(7, 1, "scope", 1, "llm", "emb", "vlm", 512, 32)
    proof = runtime.PresetProof(
        {
            name: runtime.ModelProof(name, kind, "v1", 1, "scope", True, dimension, images)
            for name, kind, dimension, images in [
                ("llm", "chat", None, False),
                ("emb", "embedding", 512, False),
                ("vlm", "vision", None, True),
            ]
        },
        True,
        "sample",
        ("tag",),
        ("A", "B"),
        (("A", "to", "B"),),
    )
    probe = AsyncMock(return_value=proof)
    departments = AsyncMock(side_effect=DepartmentNotFoundError())
    monkeypatch.setattr(runtime, "load_preset", AsyncMock(return_value=p))
    monkeypatch.setattr(runtime.ProvisionRemote, "probe_preset", probe)
    monkeypatch.setattr(department_service.DepartmentKnowledgeSpaceService, "_load_departments", departments)
    url = f"{BASE}/provider-preview"
    body = (await browser.post(url, headers=HEADERS, json=PREVIEW)).json()
    assert body["status_code"] == DepartmentNotFoundError.Code
    probe.assert_not_awaited()
    departments.side_effect = None
    departments.return_value = {20: object()}
    body = (await browser.post(url, headers=HEADERS, json=PREVIEW)).json()
    assert body["data"] == {"preset_summary": runtime.preflight(p, proof)}
    departments.assert_awaited_with([20])
    probe.assert_awaited_once_with(p)


@pytest.mark.parametrize(
    "route,body",
    [
        ("provider-preview", {"department_id": True}),
        ("provider-preview", {"department_id": -1}),
        ("batch-status", {**STATUS, "actor": 1}),
        ("batch-status", {**STATUS, "request_key": ""}),
        ("batch-status", {**STATUS, "department_ids": list(range(1, 202))}),
    ],
)
async def test_rejects_invalid_bodies(browser, route, body):
    assert (await browser.post(f"{BASE}/{route}", headers=HEADERS, json=body)).status_code == 422


async def test_batch_status_only_reads_own_scoped_create_receipts(browser, monkeypatch):
    db = create_async_engine("sqlite+aiosqlite://")
    sessions = async_sessionmaker(db)
    repo = repository.ProvisionRepository(sessions)
    monkeypatch.setattr(repository, "ProvisionRepository", lambda: repo)
    try:
        async with db.begin() as connection:
            await connection.run_sync(Op.__table__.create)
        async with sessions.begin() as session:
            for dept, tenant, actor, kind, state in [
                (10, 7, 42, "create_space", "succeeded"),
                (20, 7, 42, "create_space", "failed"),
                (30, 7, 42, "create_space", "applying"),
                (40, 7, 99, "create_space", "succeeded"),
                (50, 8, 42, "create_space", "succeeded"),
                (60, 7, 42, "update_space_settings", "succeeded"),
            ]:
                session.add(
                    Op(
                        tenant_id=tenant,
                        actor_user_id=actor,
                        operation_id=f"op-{dept}",
                        kind=kind,
                        request_key=create_item_key("batch", dept),
                        request_hash="hash",
                        remote_kb_id="redacted",
                        remote_scope_id="scope",
                        provider_instance_id=1,
                        generation=1,
                        operation_epoch=1,
                        phase="create",
                        capability_revision=1,
                        state=state,
                    )
                )
        statements = []
        event.listen(db.sync_engine, "before_cursor_execute", lambda c, cur, stmt, *args: statements.append(stmt))
        url = f"{BASE}/batch-status"
        result = (
            await browser.post(url, headers=HEADERS, json={**STATUS, "department_ids": [30, 10, 20, 40, 50, 60, 70]})
        ).json()

        def missing(i):
            return {"department_id": i, "state": "not_confirmed", "authorization": "not_confirmed"}

        assert result["data"] == {
            "items": [
                {**missing(30), "state": "applying", "operation_id": "op-30"},
                {**missing(10), "state": "succeeded", "operation_id": "op-10", "authorization": "confirmed"},
                {**missing(20), "state": "failed", "operation_id": "op-20"},
                *map(missing, [40, 50, 60, 70]),
            ]
        }
        body = (await browser.post(url, headers=HEADERS, json={**STATUS, "request_key": "different"})).json()
        assert body["data"] == {"items": [missing(20)]}
        assert len(statements) == 2 and all(s.lstrip().upper().startswith("SELECT") for s in statements)
    finally:
        await db.dispose()
