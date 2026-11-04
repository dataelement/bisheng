"""T043 覆盖 AC-04, AC-05, AC-06, AC-16, AC-19, AC-20, AC-23, AC-24。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import APIRouter, FastAPI
from sqlmodel import SQLModel, select

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.database.constants import AdminRole
from bisheng.database.models.audit_log import AuditLog
from bisheng.database.models.tenant import Tenant
from bisheng.sso_sync.application.kunlian import KunlianApiBindings
from bisheng.sso_sync.domain.models.kunlian import KunlianConnectionState, KunlianTenantBinding
from bisheng.sso_sync.domain.services.kunlian_directory import DirectoryCredential, KunlianDirectoryService
from bisheng.user.domain.models.user import User
from bisheng.user.domain.models.user_role import UserRole
from test.sso import test_kunlian_projection as projection_tests
from test.sso.test_kunlian_admission import config

owner = projection_tests.owner
directory_store = projection_tests.directory_store
projection = projection_tests.projection
BASE = "/api/v1/identity-integrations/kunlian"


@pytest.fixture
async def management_api(projection):
    from pydantic import SecretStr

    from bisheng.sso_sync.api.endpoints.kunlian import get_api_bindings
    from bisheng.sso_sync.api.router import router
    from bisheng.sso_sync.application.kunlian import KunlianManagementApplication

    projector, repository, user_owner, users, controls, _, key, _ = projection
    async with users() as session:
        for tid in (7, 8):
            tenant = await session.get(Tenant, tid)
            tenant.parent_tenant_id = 1
            session.add(tenant)
        admin = User(user_name="测试超管", password="", source="local")
        session.add(admin)
        await session.flush()
        session.add(UserRole(user_id=admin.user_id, role_id=AdminRole))
        await session.commit()
        actor = SimpleNamespace(user_id=admin.user_id, tenant_id=7, is_global_super=True)
    async with controls() as session:
        connection = await session.connection()
        await connection.run_sync(lambda sync: SQLModel.metadata.create_all(sync, tables=[AuditLog.__table__]))
    cfg = config()
    cfg.login_enabled = False

    def credential(reference):
        return DirectoryCredential("fixture-key-v1", SecretStr("private-directory-secret"))

    service = KunlianDirectoryService(repository, cfg, credential_resolver=credential)
    app_service = KunlianManagementApplication(
        service, user_owner=user_owner, tenant_owner=projector().tenant_owner, multi_tenant_enabled=True
    )
    app = FastAPI()
    api = APIRouter(prefix="/api/v1")
    api.include_router(router)
    app.include_router(api)
    app.dependency_overrides[UserPayload.get_login_user] = lambda: actor
    bindings = KunlianApiBindings(config=cfg, login=None, management=app_service)
    app.dependency_overrides[get_api_bindings] = lambda: bindings
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client, repository, user_owner, users, controls, cfg, actor, key, projector, service


async def test_status_separates_published_projection_and_unknown(management_api):
    client, _, _, _, _, cfg, _, _, _, service = management_api
    response = await client.get(BASE + "/status")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["directory_status"] == "PUBLISHED" and data["projection_status"] == "PENDING"
    assert data["member_count"] == 1 and data["projection_pending"] == 1
    assert data["directory_age_seconds"] == 0 and not data["ready"]
    assert "PROJECTION_NOT_READY" in data["reasons"]
    assert not any(
        value in response.text
        for value in ("private-directory-secret", "fixture-directory-key-ref", "display_name", "subject-1")
    )
    cfg.connection_id = "uninitialized-fixture"
    response = await client.get(BASE + "/status")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["member_count"] is None and data["directory_age_seconds"] is None and not data["ready"]
    cfg.directory_enabled = False
    service.credential_resolver = lambda reference: None
    data = (await client.get(BASE + "/status")).json()["data"]
    assert "DIRECTORY_DISABLED" in data["reasons"] and "DIRECTORY_CREDENTIAL_UNAVAILABLE" in data["reasons"]


async def test_mapping_cas_existing_tenant_and_audit(management_api):
    client, _, _, _, controls, _, actor, _, projector, _ = management_api
    path = BASE + "/tenant-bindings/external-a"
    first = (await client.get(path)).json()["data"]
    assert first["local_tenant_id"] == 7 and first["revision"] == 1
    result = await client.put(path, json={"local_tenant_id": 8, "expected_revision": 1})
    assert result.status_code == 200 and result.json()["data"]["revision"] == 2
    assert (await client.put(path, json={"local_tenant_id": 7, "expected_revision": 1})).status_code == 409
    assert (await client.put(path, json={"local_tenant_id": 999, "expected_revision": 2})).status_code == 403
    assert (await client.put(path, json={"local_tenant_id": "7", "expected_revision": 2})).status_code == 400
    assert (
        await client.put(path, json={"local_tenant_id": 7, "expected_revision": 2, "operator_id": 1})
    ).status_code == 400
    await projector().project_identity(management_api[7])
    assert (await client.put(path, json={"local_tenant_id": 7, "expected_revision": 2})).status_code == 409
    result = await client.put(path, json={"local_tenant_id": 8, "expected_revision": 2, "enabled": False})
    assert result.status_code == 200
    async with controls() as session:
        rows = (await session.exec(select(AuditLog))).all()
        assert len(rows) == 2 and all(row.operator_id == actor.user_id for row in rows)
        assert rows[0].action == "kunlian.tenant_binding.update"
        assert (await session.get(KunlianTenantBinding, ("fixture", "external-a"))).revision == 3


async def test_manual_sync_is_accepted_coalesced_and_audited(management_api):
    client, _, _, _, controls, _, actor, _, _, _ = management_api
    first = await client.post(BASE + "/sync")
    second = await client.post(BASE + "/sync")
    assert first.status_code == second.status_code == 202
    assert first.json()["data"] == second.json()["data"]
    assert first.json()["data"]["status"] == "REQUESTED"
    async with controls() as session:
        state = await session.get(KunlianConnectionState, "fixture")
        assert state.sync_requested_version > state.sync_completed_version
        rows = (await session.exec(select(AuditLog))).all()
        assert len(rows) == 2 and all(
            row.operator_id == actor.user_id and row.action == "kunlian.sync.request" for row in rows
        )


async def test_stale_super_flag_or_tenant_admin_never_grants_control_plane(management_api):
    client, _, user_owner, users, controls, _, actor, _, _, _ = management_api
    async with users() as session:
        role = (await session.exec(select(UserRole).where(UserRole.user_id == actor.user_id))).first()
        await session.delete(role)
        await session.commit()
    user_owner.global_super_checker = AsyncMock(return_value=False)
    for method, path, kwargs in (
        ("GET", "/status", {}),
        ("GET", "/tenant-bindings/external-a", {}),
        ("PUT", "/tenant-bindings/external-a", {"json": {"local_tenant_id": 7, "expected_revision": 1}}),
        ("POST", "/sync", {}),
    ):
        response = await client.request(method, BASE + path, **kwargs)
        assert response.status_code == 403
    async with controls() as session:
        assert not (await session.exec(select(AuditLog))).all()


async def test_missing_mapping_and_published_zero_are_distinct_from_unknown(management_api):
    from test.sso.test_kunlian_directory import publish

    client, repository, _, _, _, _, _, _, _, _ = management_api
    mapping = (await client.get(BASE + "/tenant-bindings/never-mapped")).json()["data"]
    assert mapping["revision"] is None and mapping["local_tenant_id"] is None
    await publish(repository, members=[])
    data = (await client.get(BASE + "/status")).json()["data"]
    assert data["directory_status"] == "PUBLISHED" and data["member_count"] == 0


async def test_audit_failure_rolls_back_mapping_and_manual_demand(management_api, monkeypatch):
    from bisheng.core.context.tenant import get_current_tenant_id, tenant_execution_scope

    client, repository, _, _, controls, _, _, _, _, _ = management_api
    async with controls() as session:
        before = (await session.get(KunlianConnectionState, "fixture")).sync_requested_version

    def unavailable(*args, **kwargs):
        raise OSError("private-audit-store-error")

    monkeypatch.setattr(repository, "_audit", unavailable)
    with tenant_execution_scope(7):
        response = await client.put(
            BASE + "/tenant-bindings/external-a", json={"local_tenant_id": 8, "expected_revision": 1}
        )
        assert response.status_code == 503 and "private-audit-store-error" not in response.text
        assert get_current_tenant_id() == 7
        assert (await client.post(BASE + "/sync")).status_code == 503
        assert get_current_tenant_id() == 7
    async with controls() as session:
        assert (await session.get(KunlianConnectionState, "fixture")).sync_requested_version == before
        row = await session.get(KunlianTenantBinding, ("fixture", "external-a"))
        assert row.local_tenant_id == 7 and row.revision == 1
        assert not (await session.exec(select(AuditLog))).all()


async def test_disabled_actor_and_invalid_target_tenant_cannot_modify(management_api):
    client, _, _, users, _, _, actor, _, _, _ = management_api
    path = BASE + "/tenant-bindings/external-a"
    async with users() as session:
        tenant = await session.get(Tenant, 8)
        tenant.status = "disabled"
        session.add(tenant)
        await session.commit()
    assert (await client.put(path, json={"local_tenant_id": 8, "expected_revision": 1})).status_code == 403
    async with users() as session:
        user = await session.get(User, actor.user_id)
        user.delete = 1
        session.add(user)
        await session.commit()
    assert (await client.get(BASE + "/status")).status_code == 403
