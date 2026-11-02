"""F114 management reads and lifecycle guards must use the same six actions."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.app_factory import AppOnlineCannotDeleteError
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.database.models.app import App
from bisheng.permission.application.identity import PermissionActor


@pytest.fixture
def management(monkeypatch):
    from bisheng.app_runtime.domain.services import app_authorization_service as policy
    from bisheng.app_runtime.domain.services.app_query_service import AppQueryService
    from bisheng.app_runtime.domain.services.app_state_service import AppStateService

    app = App(id="target", slug="example", name="Example", tenant_id=2, owner_user_id=81, state="stopped")
    actor = SimpleNamespace(user_id=42, tenant_id=2, is_global_super=False)
    allowed = set()
    monkeypatch.setattr(
        policy.AppAuthorizationService,
        "resolve_actor",
        AsyncMock(return_value=PermissionActor(subject_id=42, tenant_id=2)),
    )
    monkeypatch.setattr(
        policy, "check_business_action", AsyncMock(side_effect=lambda *a, **kw: kw["action"] in allowed)
    )
    monkeypatch.setattr(
        policy, "batch_check_business_actions", AsyncMock(side_effect=lambda *a, **kw: {app.id: frozenset(allowed)})
    )
    monkeypatch.setattr(AppQueryService, "_load", AsyncMock(return_value=app))
    monkeypatch.setattr(AppStateService, "_load", AsyncMock(return_value=app))
    return app, actor, allowed


@pytest.mark.parametrize("action", ["publish", "unpublish", "delete", "manage_permission"])
async def test_non_editor_can_read_only_safe_management_summary(management, action):
    from bisheng.app_runtime.domain.services.app_query_service import AppQueryService

    app, actor, allowed = management
    allowed.add(action)
    result = await AppQueryService.get_detail(app.id, actor=actor)
    assert action in result["allowed_actions"]
    assert result["owner_user_id"] == 81
    assert not {"manifest", "capabilities", "failure", "sealed_env", "grants", "secrets"}.intersection(result)


@pytest.mark.parametrize("entry", ["detail", "cli", "mcp"])
async def test_granted_non_owner_log_read_is_edit(management, monkeypatch, entry):
    from bisheng.app_runtime.domain.services import app_query_service as mod

    app, actor, allowed = management
    allowed.add("edit")
    logs = AsyncMock(return_value={"lines": ["safe output"]})
    monkeypatch.setattr(mod.orchestrator_client, "logs", logs)
    assert (await mod.AppQueryService.get_logs(app.id, actor=actor, entry=entry))["lines"] == ["safe output"]
    allowed.clear()
    allowed.add("publish")
    with pytest.raises(PermissionDeniedError):
        await mod.AppQueryService.get_logs(app.id, actor=actor, entry=entry)
    assert logs.await_count == 1


async def test_granted_non_owner_metadata_edit(management):
    from bisheng.app_runtime.domain.services.app_meta_service import AppMetaService

    app, actor, allowed = management
    allowed.add("edit")
    await AppMetaService._require_editor(app, actor)
    allowed.clear()
    with pytest.raises(PermissionDeniedError):
        await AppMetaService._require_editor(app, actor)


async def test_delete_is_not_tied_to_owner_status(management):
    from bisheng.app_runtime.domain.services.app_state_service import AppStateService

    app, actor, allowed = management
    allowed.add("delete")
    await AppStateService._require_deleter(app, actor)
    allowed.clear()
    with pytest.raises(PermissionDeniedError):
        await AppStateService._require_deleter(app, actor)


async def test_online_delete_still_refuses_before_runtime_work(management, monkeypatch):
    from bisheng.app_runtime.domain.services.app_state_service import AppStateService

    app, actor, allowed = management
    app.state = "online"
    allowed.add("delete")
    with pytest.raises(AppOnlineCannotDeleteError):
        await AppStateService.delete(app.id, actor=actor)


async def test_stop_and_start_are_different_actions(management):
    from bisheng.app_runtime.domain.services.app_state_service import AppStateService

    app, actor, allowed = management
    allowed.add("publish")
    await AppStateService._require_operator(app, actor)
    with pytest.raises(PermissionDeniedError):
        await AppStateService._require_operator(app, actor, operation="stop")
    allowed.clear()
    allowed.add("unpublish")
    await AppStateService._require_operator(app, actor, operation="stop")
    with pytest.raises(PermissionDeniedError):
        await AppStateService._require_operator(app, actor)


async def test_production_data_is_edit_not_owner(management):
    from bisheng.app_runtime.domain.services.app_data_service import AppDataService

    app, actor, allowed = management
    allowed.add("edit")
    await AppDataService._require_editor(app, actor)
    allowed.clear()
    allowed.add("use")
    with pytest.raises(PermissionDeniedError):
        await AppDataService._require_editor(app, actor)


async def test_data_session_checks_edit_before_creating_work(management, monkeypatch):
    from bisheng.app_runtime.domain.services.runtime_data_session_service import RuntimeDataSessionService

    app, actor, _allowed = management
    service = RuntimeDataSessionService()
    start = AsyncMock()
    monkeypatch.setattr(service, "_start", start)
    with pytest.raises(PermissionDeniedError):
        await service.execute(app, actor, "tables", {})
    start.assert_not_awaited()


async def test_data_grant_rechecks_edit_before_signing(management, monkeypatch):
    from contextlib import asynccontextmanager

    from bisheng.app_runtime.domain.services.runtime_data_grant_service import RuntimeDataGrantService

    app, actor, _allowed = management

    @asynccontextmanager
    async def transaction():
        yield None

    repo = SimpleNamespace(transaction=transaction, get_application=AsyncMock(return_value=app), get=AsyncMock())
    service = RuntimeDataGrantService(repository=repo)
    monkeypatch.setattr(service, "_keys", lambda: ("active", {}))
    with pytest.raises(PermissionDeniedError):
        await service.issue(app, actor, SimpleNamespace(id="operation"), {}, "tables", {})
    repo.get.assert_not_awaited()


@pytest.mark.parametrize(
    "purpose,actions",
    [("release_submit", {"edit", "publish"}), ("approved_start", {"publish"}), ("config_restart", {"edit", "publish"})],
)
async def test_cancel_requires_current_canceller_actions(management, purpose, actions):
    from contextlib import asynccontextmanager

    from bisheng.app_runtime.domain.services.runtime_management_service import RuntimeManagementService

    app, actor, allowed = management
    op = SimpleNamespace(
        id="op",
        version_id="version",
        app_id=app.id,
        tenant_id=app.tenant_id,
        stage="preparing",
        status="running",
        payload={
            "authorization_context": {
                "schema": 1,
                "origin_kind": "user_request",
                "purpose": purpose,
                "target": {"tenant_id": app.tenant_id, "app_id": app.id, "version_id": "version"},
                "required_actions": sorted(actions),
            }
        },
    )

    @asynccontextmanager
    async def transaction():
        yield None

    repo = SimpleNamespace(
        get_application=AsyncMock(return_value=app),
        get=AsyncMock(return_value=op),
        save=AsyncMock(),
        transaction=transaction,
    )
    service = RuntimeManagementService(repository=repo)
    allowed.update(actions - {"publish"})
    with pytest.raises(PermissionDeniedError):
        await service.cancel(app.id, op.id, actor)
    repo.save.assert_not_awaited()
    allowed.update(actions)
    assert (await service.cancel(app.id, op.id, actor))["cancel_requested"]
    repo.save.assert_awaited_once()


@pytest.mark.parametrize(
    "context",
    [
        None,
        {"schema": 1, "origin_kind": "system_recovery", "purpose": "system_recovery"},
        {"schema": 1, "origin_kind": "user_request", "purpose": "unknown"},
    ],
)
async def test_cancel_rejects_missing_or_system_source(management, context):
    from contextlib import asynccontextmanager

    from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict
    from bisheng.app_runtime.domain.services.runtime_management_service import RuntimeManagementService

    app, actor, allowed = management
    allowed.update({"edit", "publish", "unpublish", "delete"})
    op = SimpleNamespace(
        id="op",
        version_id="version",
        app_id=app.id,
        tenant_id=app.tenant_id,
        stage="preparing",
        status="running",
        payload={"authorization_context": context},
    )

    @asynccontextmanager
    async def transaction():
        yield None

    repo = SimpleNamespace(
        get_application=AsyncMock(return_value=app),
        get=AsyncMock(return_value=op),
        save=AsyncMock(),
        transaction=transaction,
    )
    with pytest.raises((RuntimeConflict, PermissionDeniedError)):
        await RuntimeManagementService(repository=repo).cancel(app.id, op.id, actor)
    repo.save.assert_not_awaited()


async def test_private_runtime_snapshot_requires_edit(management):
    from bisheng.app_runtime.domain.services.runtime_management_service import RuntimeManagementService

    app, actor, allowed = management
    repo = SimpleNamespace(get_application=AsyncMock(return_value=app), find=AsyncMock(return_value=[]))
    allowed.add("publish")
    with pytest.raises(PermissionDeniedError):
        await RuntimeManagementService(repository=repo).snapshots(app.id, actor)
    repo.find.assert_not_awaited()
    allowed.add("edit")
    assert await RuntimeManagementService(repository=repo).snapshots(app.id, actor) == []
