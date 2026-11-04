"""F114 AC-01 through AC-08, AC-62, AC-63 and AC-65: exact action boundaries."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.app_runtime.domain.schemas.app_authorization import APP_ACTIONS, AppOperation, required_actions
from bisheng.common.errcode.app_factory import AppNotFoundError
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.permission.application.identity import PermissionActor


@pytest.fixture
def authorization(monkeypatch):
    from bisheng.app_runtime.domain.services import app_authorization_service as mod

    app = SimpleNamespace(id="target", tenant_id=2, owner_user_id=81, state="stopped")
    actor = PermissionActor(subject_type="user", subject_id=42, tenant_id=2)
    checker = AsyncMock(return_value=False)
    monkeypatch.setattr(mod.AppAuthorizationService, "load_app", AsyncMock(return_value=app))
    monkeypatch.setattr(mod.AppAuthorizationService, "resolve_actor", AsyncMock(return_value=actor))
    monkeypatch.setattr(mod, "check_business_action", checker)
    return mod, app, actor, checker


@pytest.mark.parametrize("action", [value for value in APP_ACTIONS if value != "use"])
async def test_exact_action_controls_operation(authorization, action):
    mod, app, actor, checker = authorization
    operation = {
        "use": None,
        "edit": "metadata_edit",
        "publish": "approved_start",
        "unpublish": "stop",
        "delete": "destroy",
        "manage_permission": "grant_manage",
    }[action]
    if operation is None:
        return
    checker.return_value = True
    result = await mod.AppAuthorizationService.authorize_app(actor, app.id, operation)
    assert result is app
    assert checker.await_args.kwargs["action"] == action
    assert app.owner_user_id == 81
    assert app.tenant_id == 2


async def test_use_only_cannot_read_management(authorization):
    mod, app, actor, checker = authorization
    checker.side_effect = lambda *a, **kw: kw["action"] == "use"
    with pytest.raises(PermissionDeniedError):
        await mod.AppAuthorizationService.authorize_app(actor, app.id, "management_read")
    assert {call.kwargs["action"] for call in checker.await_args_list} == set(APP_ACTIONS) - {"use"}


@pytest.mark.parametrize("action", ["edit", "publish", "unpublish", "delete", "manage_permission"])
async def test_any_management_action_can_read_safe_basics(authorization, action):
    mod, app, actor, checker = authorization
    checker.side_effect = lambda *a, **kw: kw["action"] == action
    assert await mod.AppAuthorizationService.authorize_app(actor, app.id, "management_read") is app


@pytest.mark.parametrize("missing", ["edit", "publish"])
async def test_rebuild_requires_both_actions(authorization, missing):
    mod, app, actor, checker = authorization
    checker.side_effect = lambda *a, **kw: kw["action"] != missing
    with pytest.raises(PermissionDeniedError) as caught:
        await mod.AppAuthorizationService.authorize_app(actor, app.id, "config_restart")
    assert caught.value.kwargs["required_actions"] == ["edit", "publish"]


@pytest.mark.parametrize("state,tenant", [("deleted", 2), ("stopped", 3)])
async def test_target_facts_checked_before_admin_shortcut(authorization, state, tenant):
    mod, app, actor, checker = authorization
    actor = PermissionActor(subject_id=42, tenant_id=2, super_admin=True)
    mod.AppAuthorizationService.resolve_actor.return_value = actor
    app.state, app.tenant_id = state, tenant
    checker.return_value = True
    with pytest.raises(AppNotFoundError):
        await mod.AppAuthorizationService.authorize_app(actor, app.id, "destroy")
    checker.assert_not_awaited()


async def test_service_account_actor_is_not_the_resource_owner(authorization):
    mod, app, actor, checker = authorization
    actor = PermissionActor(subject_type="service_account", subject_id=24, tenant_id=2)
    mod.AppAuthorizationService.resolve_actor.return_value = actor
    checker.return_value = True
    await mod.AppAuthorizationService.authorize_app(actor, app.id, "metadata_edit")
    assert checker.await_args.kwargs["actor"].fga_subject == "service_account:24"


async def test_unknown_or_unavailable_never_grants(authorization):
    mod, app, actor, checker = authorization
    with pytest.raises(PermissionDeniedError):
        await mod.AppAuthorizationService.authorize_app(actor, app.id, "runtime_upgrade")
    checker.assert_not_awaited()
    checker.side_effect = RuntimeError("permission backend unavailable")
    with pytest.raises(RuntimeError):
        await mod.AppAuthorizationService.authorize_app(actor, app.id, "metadata_edit")


def test_restore_and_cancel_require_original_purpose():
    assert required_actions(AppOperation.RESTORE) == ("edit",)
    assert required_actions(AppOperation.RESTORE, resume=True) == ("edit", "publish")
    assert required_actions("config_restart") == ("edit", "publish")
    with pytest.raises(ValueError):
        required_actions("system_recovery")


async def test_disabled_catalog_action_does_not_hide_other_management_actions(authorization):
    from bisheng.common.errcode.permission import InvalidCatalogActionError

    mod, app, actor, checker = authorization

    def decide(*args, **kwargs):
        if kwargs["action"] == "edit":
            raise InvalidCatalogActionError()
        return kwargs["action"] == "publish"

    checker.side_effect = decide
    assert await mod.AppAuthorizationService.authorize_app(actor, app.id, "management_read") is app


async def test_permission_for_another_app_is_not_reused(authorization):
    mod, app, actor, checker = authorization
    checker.side_effect = lambda *a, **kw: kw["resource_id"] == "other-app"
    with pytest.raises(PermissionDeniedError):
        await mod.AppAuthorizationService.authorize_app(actor, app.id, "destroy")


async def test_missing_real_credential_actor_cannot_fall_back_to_owner(monkeypatch):
    from bisheng.app_runtime.domain.services import app_authorization_service as mod

    monkeypatch.setattr(
        mod,
        "get_current_open_api_principal",
        lambda: SimpleNamespace(authorization_subject_type="service_account", authorization_subject_id=24, tenant_id=2),
    )
    monkeypatch.setattr(mod, "get_current_permission_actor", lambda: None)
    with pytest.raises(PermissionDeniedError):
        await mod.AppAuthorizationService.resolve_actor(SimpleNamespace(user_id=81, tenant_id=2))
