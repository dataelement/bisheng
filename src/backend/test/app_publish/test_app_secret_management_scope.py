"""Browser management reads use the application's tenant without granting secret writes."""

import json
from contextlib import contextmanager
from unittest.mock import AsyncMock

import pytest

from test.app_publish.test_app_secret_repository import secret_repository as secret_repository


@pytest.fixture()
def management_scope(monkeypatch):
    from bisheng.common.services.config_service import settings
    from bisheng.core.context import tenant
    from bisheng.core.database import tenant_filter

    monkeypatch.setattr(settings.multi_tenant, "enabled", True)
    tenant_filter.register_tenant_filter_events()

    @contextmanager
    def scope(actor_tenant=1, selected=None, *, all_tenants=True):
        with tenant.tenant_execution_scope(actor_tenant):
            tenant.set_is_management_api(True)
            tenant.set_admin_scope_tenant_id(selected)
            tenant.set_visible_tenant_ids(frozenset({selected or actor_tenant}))
            tenant.set_management_all_tenants(all_tenants)
            yield

    return scope


async def child_environment(secret_repository, app_factory, owner_user):
    from bisheng.app_publish.domain.services.app_secret_service import AppSecretService

    repo, cipher = secret_repository
    app, version = await app_factory(tenant_id=2)
    owner = owner_user.payload.model_copy(update={"tenant_id": 2})
    service = AppSecretService(repository=repo, cipher=cipher)
    async with repo.transaction() as session:
        version.capabilities = {"secrets": [{"name": "DECLARED"}]}
        session.add(version)
    await service.save(app.id, "DECLARED", value="private-child-value", expected_revision=0, actor=owner)
    await service.save(app.id, "UNREFERENCED", value="private-unused-value", expected_revision=1, actor=owner)
    return app, service


@pytest.mark.parametrize("selected", [None, 2])
async def test_super_admin_reads_child_summary_in_management_view(
    secret_repository, app_factory, owner_user, super_admin_user, management_scope, selected
):
    from bisheng.core.context import tenant

    app, service = await child_environment(secret_repository, app_factory, owner_user)
    with management_scope(selected=selected, all_tenants=selected is None):
        result = await service.get(app.id, actor=super_admin_user.payload)
        assert result["revision"] == 2
        assert result["items"] == [
            {"name": "DECLARED", "present": True, "approved_reference": True, "pending_reference": False}
        ]
        assert "private-child-value" not in json.dumps(result)
        assert "private-unused-value" not in json.dumps(result)
        assert tenant.get_current_tenant_id() == (selected or 1)
        assert tenant.current_tenant_id.get() == 1
        assert tenant.get_admin_scope_tenant_id() == selected
        assert tenant.is_management_all_tenants() == (selected is None)


async def test_management_view_cannot_bypass_other_tenant_selection(
    secret_repository, app_factory, owner_user, super_admin_user, management_scope
):
    from bisheng.common.errcode.app_factory import AppNotFoundError

    app, service = await child_environment(secret_repository, app_factory, owner_user)
    with management_scope(selected=3, all_tenants=False), pytest.raises(AppNotFoundError):
        await service.get(app.id, actor=super_admin_user.payload)


async def test_non_super_cannot_use_management_context_to_read_another_tenant(
    secret_repository, app_factory, owner_user, management_scope
):
    from bisheng.common.errcode.app_factory import AppNotFoundError
    from bisheng.core.context import tenant

    app, service = await child_environment(secret_repository, app_factory, owner_user)
    with management_scope(actor_tenant=3):
        actor = owner_user.payload.model_copy(update={"tenant_id": 3})
        with pytest.raises(AppNotFoundError):
            await service.get(app.id, actor=actor)
        assert tenant.get_current_tenant_id() == 3
        assert tenant.is_management_all_tenants()


async def test_same_tenant_reader_without_edit_receives_management_denial(
    secret_repository, app_factory, owner_user, management_scope, monkeypatch
):
    from bisheng.app_publish.domain.services import app_secret_service
    from bisheng.common.errcode.app_factory import AppManageForbiddenError
    from bisheng.permission.application import business_authorization

    app, service = await child_environment(secret_repository, app_factory, owner_user)
    monkeypatch.setattr(app_secret_service, "check_tenant_admin", AsyncMock(return_value=False))
    monkeypatch.setattr(business_authorization, "check_business_action", AsyncMock(return_value=False))
    actor = owner_user.payload.model_copy(update={"user_id": 123, "tenant_id": 2})
    with management_scope(actor_tenant=2, all_tenants=False), pytest.raises(AppManageForbiddenError):
        await service.get(app.id, actor=actor)


async def test_super_admin_read_does_not_grant_secret_mutation(
    secret_repository, app_factory, owner_user, super_admin_user, management_scope
):
    from bisheng.common.errcode.app_publish import AppPublishOwnerOnlyError

    app, service = await child_environment(secret_repository, app_factory, owner_user)
    with management_scope():
        await service.get(app.id, actor=super_admin_user.payload)
        with pytest.raises(AppPublishOwnerOnlyError):
            await service.save(
                app.id, "DECLARED", value="replacement", expected_revision=2, actor=super_admin_user.payload
            )
        with pytest.raises(AppPublishOwnerOnlyError):
            await service.delete(app.id, "DECLARED", expected_revision=2, actor=super_admin_user.payload)
        assert (await service.get(app.id, actor=super_admin_user.payload))["revision"] == 2


async def test_management_api_reports_summary_success_and_owner_write_refusal(
    secret_repository, app_factory, owner_user, super_admin_user, management_scope, api_app, monkeypatch
):
    from bisheng.app_publish.api.endpoints import app_secrets

    app, service = await child_environment(secret_repository, app_factory, owner_user)
    monkeypatch.setattr(app_secrets, "service", lambda: service)
    with management_scope():
        async with api_app(payload=super_admin_user.payload) as client:
            response = await client.get(f"/api/v1/apps/{app.id}/secrets")
            assert response.status_code == 200 and response.json()["status_code"] == 200
            assert response.json()["data"]["items"] == [
                {"name": "DECLARED", "present": True, "approved_reference": True, "pending_reference": False}
            ]
            assert "private-child-value" not in response.text
            refused = await client.put(
                f"/api/v1/apps/{app.id}/secrets/DECLARED", json={"value": "replacement", "expected_revision": 2}
            )
            assert refused.status_code == 200 and refused.json()["status_code"] == 16254
            missing = await client.get("/api/v1/apps/missing/secrets")
            assert missing.status_code == 200 and missing.json()["status_code"] == 16101


@pytest.mark.parametrize("can_edit", [False, True])
async def test_management_api_uses_existing_editor_permissions(
    secret_repository, app_factory, owner_user, management_scope, api_app, monkeypatch, can_edit
):
    from bisheng.app_publish.api.endpoints import app_secrets
    from bisheng.app_publish.domain.services import app_secret_service
    from bisheng.permission.application import business_authorization

    app, service = await child_environment(secret_repository, app_factory, owner_user)
    monkeypatch.setattr(app_secrets, "service", lambda: service)
    monkeypatch.setattr(app_secret_service, "check_tenant_admin", AsyncMock(return_value=False))
    check = AsyncMock(return_value=can_edit)
    monkeypatch.setattr(business_authorization, "check_business_action", check)
    actor = owner_user.payload.model_copy(update={"user_id": 123, "tenant_id": 2})
    with management_scope(actor_tenant=2, all_tenants=False):
        async with api_app(payload=actor) as client:
            response = await client.get(f"/api/v1/apps/{app.id}/secrets")
        assert response.status_code == 200
        assert response.json()["status_code"] == (200 if can_edit else 16106)
        check.assert_awaited_once_with(actor, resource_type="app", resource_id=app.id, action="edit")


@pytest.mark.parametrize("snapshot_fails", [False, True])
async def test_running_environment_read_restores_management_scope_on_success_and_failure(
    secret_repository, app_factory, owner_user, super_admin_user, management_scope, monkeypatch, snapshot_fails
):
    from bisheng.app_runtime.application import runtime_secrets
    from bisheng.core.context import tenant

    app, service = await child_environment(secret_repository, app_factory, owner_user)
    async with service.repo.transaction() as session:
        app.state = "online"
        session.add(app)
    monkeypatch.setattr(runtime_secrets, "rebuild_status", AsyncMock(return_value=None))

    async def running_snapshot(app_id, *, session):
        assert app_id == app.id
        assert tenant.get_current_tenant_id() == 2
        assert tenant.is_strict_tenant_filter()
        assert not tenant.is_management_all_tenants()
        if snapshot_fails:
            raise RuntimeError("running snapshot unavailable")
        return runtime_secrets.RunningEnvironmentSnapshot(
            operation_id="running-operation",
            version_id=app.current_version_id,
            route_epoch=7,
            env={"DECLARED": "private-child-value"},
        )

    service.running_snapshot = running_snapshot
    with management_scope():
        if snapshot_fails:
            with pytest.raises(RuntimeError, match="running snapshot unavailable"):
                await service.get(app.id, actor=super_admin_user.payload)
        else:
            result = await service.get(app.id, actor=super_admin_user.payload)
            assert result["runtime"]["comparison"] == "same"
            assert result["runtime"]["route_epoch"] == 7
            assert "private-child-value" not in json.dumps(result)
        assert tenant.get_current_tenant_id() == 1
        assert tenant.is_management_all_tenants()
        assert not tenant.is_strict_tenant_filter()
