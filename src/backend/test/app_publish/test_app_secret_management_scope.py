"""F114 concrete management scopes retain F048 edit and mask environment values."""

import json
from contextlib import contextmanager
from unittest.mock import AsyncMock

import pytest
from sqlmodel import select

from test.app_publish.test_app_secret_repository import secret_repository as secret_repository


@pytest.fixture(autouse=True)
def authorization_ports(monkeypatch, publish_db):
    from bisheng.app_runtime.domain.services import app_authorization_service
    from bisheng.core.context.tenant import strict_tenant_filter
    from bisheng.database.models.app import App
    from bisheng.permission.application import relation_api

    async def load_app(app_id):
        with strict_tenant_filter():
            async with publish_db() as session:
                return (await session.exec(select(App).where(App.id == app_id))).first()

    monkeypatch.setattr(relation_api, "is_tenant_admin", AsyncMock(return_value=False))
    check = AsyncMock(return_value=True)
    monkeypatch.setattr(app_authorization_service.AppAuthorizationService, "load_app", load_app)
    monkeypatch.setattr(app_authorization_service, "check_business_action", check)
    return check


@pytest.fixture()
def management_scope(monkeypatch):
    from bisheng.common.services.config_service import settings
    from bisheng.core.context import tenant
    from bisheng.core.database import tenant_filter

    monkeypatch.setattr(settings.multi_tenant, "enabled", True)
    tenant_filter.register_tenant_filter_events()

    @contextmanager
    def scope(actor_tenant=1, selected=None, *, legacy_global=False):
        with tenant.tenant_execution_scope(actor_tenant):
            tenant.set_is_management_api(True)
            tenant.set_admin_scope_tenant_id(selected)
            tenant.set_visible_tenant_ids(frozenset({selected or actor_tenant}))
            tenant.set_management_all_tenants(legacy_global)
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


async def test_super_admin_reads_only_selected_child_summary(
    secret_repository, app_factory, owner_user, super_admin_user, management_scope
):
    from bisheng.core.context import tenant

    app, service = await child_environment(secret_repository, app_factory, owner_user)
    with management_scope(selected=2):
        result = await service.get(app.id, actor=super_admin_user.payload)
        assert result["revision"] == 2
        assert [item["name"] for item in result["items"]] == ["DECLARED", "UNREFERENCED"]
        assert all(item["present"] and item["mask"] == "••••••" for item in result["items"])
        assert result["items"][0]["approved_reference"]
        assert not result["items"][1]["approved_reference"]
        assert "private-child-value" not in json.dumps(result)
        assert "private-unused-value" not in json.dumps(result)
        assert tenant.get_current_tenant_id() == 2
        assert tenant.current_tenant_id.get() == 1
        assert tenant.get_admin_scope_tenant_id() == 2
        assert not tenant.is_management_all_tenants()


@pytest.mark.parametrize("selected,legacy_global", [(None, False), (None, True), (3, False)])
async def test_management_view_cannot_bypass_concrete_tenant_selection(
    secret_repository, app_factory, owner_user, super_admin_user, management_scope, selected, legacy_global
):
    from bisheng.common.errcode.app_factory import AppNotFoundError

    app, service = await child_environment(secret_repository, app_factory, owner_user)
    with management_scope(selected=selected, legacy_global=legacy_global), pytest.raises(AppNotFoundError):
        await service.get(app.id, actor=super_admin_user.payload)


async def test_non_super_cannot_forge_a_selected_tenant(
    secret_repository, app_factory, owner_user, management_scope, authorization_ports
):
    from bisheng.common.errcode.app_factory import AppNotFoundError

    app, service = await child_environment(secret_repository, app_factory, owner_user)
    authorization_ports.reset_mock()
    with management_scope(actor_tenant=3, selected=2), pytest.raises(AppNotFoundError):
        await service.get(app.id, actor=owner_user.payload.model_copy(update={"tenant_id": 3}))
    authorization_ports.assert_not_awaited()


@pytest.mark.parametrize("can_edit", [False, True])
async def test_same_tenant_reader_uses_edit_instead_of_owner_shortcut(
    secret_repository, app_factory, owner_user, management_scope, authorization_ports, can_edit
):
    from bisheng.common.errcode.permission import PermissionDeniedError

    app, service = await child_environment(secret_repository, app_factory, owner_user)
    authorization_ports.reset_mock()
    authorization_ports.return_value = can_edit
    actor = owner_user.payload.model_copy(update={"user_id": 123, "tenant_id": 2})
    with management_scope(actor_tenant=2):
        if can_edit:
            assert (await service.get(app.id, actor=actor))["revision"] == 2
        else:
            with pytest.raises(PermissionDeniedError):
                await service.get(app.id, actor=actor)
    assert authorization_ports.await_count == 1
    assert authorization_ports.await_args.kwargs["action"] == "edit"
    assert authorization_ports.await_args.kwargs["actor"].subject_id == 123


async def test_selected_super_admin_mutations_follow_edit_and_revision_control(
    secret_repository, app_factory, owner_user, super_admin_user, management_scope, authorization_ports
):
    from bisheng.common.errcode.permission import PermissionDeniedError

    app, service = await child_environment(secret_repository, app_factory, owner_user)
    with management_scope(selected=2):
        authorization_ports.return_value = False
        with pytest.raises(PermissionDeniedError):
            await service.save(app.id, "DECLARED", value="replacement", expected_revision=2, actor=super_admin_user.payload)
        with pytest.raises(PermissionDeniedError):
            await service.delete(app.id, "DECLARED", expected_revision=2, actor=super_admin_user.payload)
        authorization_ports.return_value = True
        assert (await service.get(app.id, actor=super_admin_user.payload))["revision"] == 2
        saved = await service.save(app.id, "DECLARED", value="replacement", expected_revision=2, actor=super_admin_user.payload)
        assert saved["revision"] == 3
        assert (await service.delete(app.id, "UNREFERENCED", expected_revision=3, actor=super_admin_user.payload))["revision"] == 4


@pytest.mark.parametrize("can_edit", [False, True])
async def test_management_api_uses_editor_permissions_and_masks_values(
    secret_repository, app_factory, owner_user, management_scope, api_app, monkeypatch, authorization_ports, can_edit
):
    from bisheng.app_publish.api.endpoints import app_secrets
    from bisheng.common.errcode.permission import PermissionDeniedError

    app, service = await child_environment(secret_repository, app_factory, owner_user)
    monkeypatch.setattr(app_secrets, "service", lambda: service)
    authorization_ports.return_value = can_edit
    actor = owner_user.payload.model_copy(update={"user_id": 123, "tenant_id": 2})
    with management_scope(actor_tenant=2):
        async with api_app(payload=actor) as client:
            response = await client.get(f"/api/v1/apps/{app.id}/secrets")
            missing = await client.get("/api/v1/apps/missing/secrets")
        assert response.status_code == 200
        assert response.json()["status_code"] == (200 if can_edit else PermissionDeniedError.Code)
        assert missing.json()["status_code"] == 16101
        assert "private-child-value" not in response.text
        assert "private-unused-value" not in response.text


@pytest.mark.parametrize("snapshot_fails", [False, True])
async def test_running_environment_read_restores_concrete_management_scope(
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
            operation_id="running-operation", version_id=app.current_version_id, route_epoch=7,
            env={"DECLARED": "private-child-value"},
        )

    service.running_snapshot = running_snapshot
    with management_scope(selected=2):
        if snapshot_fails:
            with pytest.raises(RuntimeError, match="running snapshot unavailable"):
                await service.get(app.id, actor=super_admin_user.payload)
        else:
            result = await service.get(app.id, actor=super_admin_user.payload)
            assert result["runtime"]["comparison"] == "same"
            assert result["runtime"]["route_epoch"] == 7
            assert "private-child-value" not in json.dumps(result)
        assert tenant.current_tenant_id.get() == 1
        assert tenant.get_current_tenant_id() == 2
        assert tenant.get_is_management_api()
        assert not tenant.is_strict_tenant_filter()
