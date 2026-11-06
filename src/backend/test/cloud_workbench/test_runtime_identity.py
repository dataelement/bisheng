"""Desktop publishing follows the current delayed runtime authorization contract."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.app_publish.domain.services.desktop_publish_service import publish_identity
from bisheng.common.errcode.dsh import DshSessionRevokedError
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.dsh.domain.services.access import DshPrincipal
from bisheng.permission.application.identity import resolve_permission_actor
from test.app_runtime.test_f114_execution_authorization import origin as origin


@pytest.fixture
def desktop_reference():
    principal = DshPrincipal(tenant_id="3", user_id="42", session_id="desktop-device", session_version=2)
    return {"kind": "dsh_session", "principal": principal.model_dump()}


async def test_publish_identity_retains_current_actor_and_session(desktop_reference):
    principal = DshPrincipal.model_validate(desktop_reference["principal"])
    actor = SimpleNamespace(user_id=42, tenant_id=3, user_name="editor", is_global_super=True)
    identity = publish_identity(actor, 81, principal)
    permission_actor = await resolve_permission_actor(identity)
    assert permission_actor.subject_id == 42 and permission_actor.super_admin
    assert identity.resource_owner_user_id == 81
    assert identity._runtime_credential_reference == desktop_reference
    assert identity.credential_id is None


async def test_desktop_origin_is_revalidated_before_runtime_effect(origin, desktop_reference, monkeypatch):
    module, app, identity = origin
    identity._runtime_credential_reference = desktop_reference
    context = await module.RuntimeAuthorizationService.capture_user(identity, app, "release_submit", version_id="v2")
    assert context["credential_ref"] == desktop_reference
    assert context["self_review_user_id"] == 42
    resolved = AsyncMock(return_value=identity)
    monkeypatch.setattr(module, "resolve_desktop_runtime_identity", resolved)
    await module.RuntimeAuthorizationService.validate_user(context, app, version_id="v2")
    resolved.assert_awaited_once_with(desktop_reference)
    resolved.side_effect = DshSessionRevokedError()
    with pytest.raises(DshSessionRevokedError):
        await module.RuntimeAuthorizationService.validate_user(context, app, version_id="v2")


async def test_desktop_runtime_rechecks_current_session_and_identity(desktop_reference, monkeypatch):
    from bisheng.dsh.application import runtime_identity as module

    runtime = SimpleNamespace(
        sessions=SimpleNamespace(validate=AsyncMock()),
        identity=SimpleNamespace(
            check=AsyncMock(return_value=SimpleNamespace(active=True, user=SimpleNamespace(username="current-name")))
        ),
        close=AsyncMock(),
    )
    monkeypatch.setattr(module, "get_settings", lambda: SimpleNamespace(enabled=True))
    monkeypatch.setattr(module.DshSettingsService, "require_enabled", AsyncMock())
    monkeypatch.setattr(module, "build_runtime", AsyncMock(return_value=runtime))
    login = AsyncMock(return_value=SimpleNamespace(user_id=42, tenant_id=3))
    monkeypatch.setattr(module.UserPayload, "init_login_user", login)
    identity = await module.resolve_desktop_runtime_identity(desktop_reference)
    assert (identity.user_id, identity.tenant_id) == (42, 3)
    runtime.sessions.validate.assert_awaited_once_with(DshPrincipal.model_validate(desktop_reference["principal"]))
    login.assert_awaited_once_with(user_id=42, user_name="current-name", tenant_id=3)
    runtime.close.assert_awaited_once()
    runtime.sessions.validate.side_effect = DshSessionRevokedError()
    login.reset_mock()
    runtime.identity.check.reset_mock()
    with pytest.raises(DshSessionRevokedError):
        await module.resolve_desktop_runtime_identity(desktop_reference)
    login.assert_not_awaited()
    runtime.identity.check.assert_not_awaited()
    assert runtime.close.await_count == 2


async def test_disabled_desktop_cannot_resume_runtime_work(desktop_reference, monkeypatch):
    from bisheng.dsh.application import runtime_identity as module

    monkeypatch.setattr(module, "get_settings", lambda: SimpleNamespace(enabled=False))
    build = AsyncMock()
    monkeypatch.setattr(module, "build_runtime", build)
    with pytest.raises(PermissionDeniedError) as denied:
        await module.resolve_desktop_runtime_identity(desktop_reference)
    assert denied.value.kwargs["reason"] == "runtime_desktop_disabled"
    build.assert_not_awaited()
