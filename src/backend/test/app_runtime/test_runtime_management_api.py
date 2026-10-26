"""ASGI boundary with real services/repository; only login and object storage are ports."""

from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from bisheng.app_runtime.api.endpoints import runtime_management as api
from bisheng.app_runtime.domain.services import runtime_management_service, runtime_profile_service
from bisheng.app_runtime.domain.services.runtime_management_service import RuntimeManagementService
from bisheng.app_runtime.domain.services.runtime_profile_service import RuntimeProfileService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from test.app_runtime.test_runtime_artifacts import MemoryObjects
from test.app_runtime.test_runtime_delivery_repository import runtime_repo as runtime_repo
from test.app_runtime.test_runtime_profiles import definition


@pytest.fixture
async def management_api(runtime_repo, monkeypatch):
    actors = {
        "owner": SimpleNamespace(subject_type="user", subject_id=10, tenant_id=1, super_admin=False),
        "other": SimpleNamespace(subject_type="user", subject_id=11, tenant_id=1, super_admin=False),
        "foreign": SimpleNamespace(subject_type="user", subject_id=10, tenant_id=2, super_admin=True),
        "admin": SimpleNamespace(subject_type="user", subject_id=2, tenant_id=1, super_admin=True),
    }

    async def resolve(actor):
        return actor

    async def application(app):
        return SimpleNamespace(id=app, tenant_id=1, owner_user_id=10, state="online", current_version_id="version-a")

    monkeypatch.setattr(runtime_profile_service, "resolve_permission_actor", resolve)
    monkeypatch.setattr(runtime_management_service, "resolve_permission_actor", resolve)
    monkeypatch.setattr(runtime_repo, "get_application", application)
    profile = RuntimeProfileService(runtime_repo)
    management = RuntimeManagementService(runtime_repo, MemoryObjects())
    monkeypatch.setattr(api, "RuntimeProfileService", lambda: profile)
    monkeypatch.setattr(api, "RuntimeManagementService", lambda: management)
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1")

    async def login(request: Request):
        return actors[request.headers["x-fixture-actor"]]

    app.dependency_overrides[UserPayload.get_login_user] = login

    @app.exception_handler(BaseErrorCode)
    async def business_error(_request, error):
        return JSONResponse(jsonable_encoder(error.return_resp_instance()))

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture") as client:
        yield client


async def test_profile_import_default_and_read_contract(management_api):
    """AC-14, AC-15: immutable import plus default CAS is usable through real HTTP routes."""
    client = management_api
    headers = {"x-fixture-actor": "admin"}
    created = (await client.post("/api/v1/runtime/profiles", headers=headers, json=definition())).json()
    assert created["status_code"] == 200
    selected = created["data"]["id"]
    response = await client.put(
        "/api/v1/runtime/profiles/default",
        headers=headers,
        json={
            "language": "python3.11",
            "profile_id": selected,
            "expected_generation": 0,
        },
    )
    assert response.json()["status_code"] == 200
    read = (await client.get("/api/v1/runtime/profiles/defaults", headers={"x-fixture-actor": "owner"})).json()
    assert read["data"][0]["profile_id"] == selected
    assert read["data"][0]["generation"] == 1
    failed = await client.put(
        "/api/v1/runtime/profiles/default",
        headers=headers,
        json={
            "language": "python3.11",
            "profile_id": selected,
            "expected_generation": 0,
        },
    )
    assert failed.json()["status_code"] == 16166


@pytest.mark.parametrize("actor", ["other", "foreign", "admin"])
async def test_all_nonowners_are_refused_before_snapshot_or_restore(management_api, actor):
    """AC-30, AC-45: super admin and foreign users cannot substitute for the app owner."""
    headers = {"x-fixture-actor": actor}
    snapshots = await management_api.get("/api/v1/apps/app-a/runtime/snapshots", headers=headers)
    assert snapshots.json()["status_code"] == 16105
    state = await management_api.get("/api/v1/apps/app-a/runtime/state", headers=headers)
    assert state.json()["status_code"] == 16105
    restore = await management_api.post(
        "/api/v1/apps/app-a/runtime/restore",
        headers=headers,
        json={
            "snapshot_id": "unknown",
            "expected_current_generation": 1,
            "acknowledge_data_loss": True,
            "idempotency_key": "fixture-restore-denied",
        },
    )
    assert restore.json()["status_code"] == 16105


async def test_owner_snapshot_read_is_allowed_but_global_import_is_refused(management_api):
    """AC-14, AC-41: an owner's data access does not grant global catalog writes."""
    headers = {"x-fixture-actor": "owner"}
    response = await management_api.get("/api/v1/apps/app-a/runtime/snapshots", headers=headers)
    assert response.json()["data"] == []
    denied = await management_api.post("/api/v1/runtime/profiles", headers=headers, json=definition())
    assert denied.json()["status_code"] == 16106


async def test_owner_reads_current_fence_before_restore(management_api, runtime_repo):
    from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeAssignment

    await runtime_repo.save(
        RuntimeAssignment(
            tenant_id=1, app_id="app-a", node_id="node-a", generation=7, owner_epoch=1, active_operation_id="op-a"
        )
    )
    response = await management_api.get("/api/v1/apps/app-a/runtime/state", headers={"x-fixture-actor": "owner"})
    body = response.json()
    assert body["status_code"] == 200
    assert body["data"] == {
        "app_id": "app-a",
        "state": "online",
        "current_version_id": "version-a",
        "generation": 7,
        "operation_id": "op-a",
    }
