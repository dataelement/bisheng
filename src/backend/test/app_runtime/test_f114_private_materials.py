"""Private material selection uses app.edit, independent of natural ownership."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.app_publish import AppNotOwnedBySubjectError
from bisheng.common.errcode.permission import PermissionDeniedError


@pytest.mark.parametrize("kind", ["natural_person", "service_account"])
async def test_granted_non_owner_can_select_private_materials(monkeypatch, kind):
    """AC-27、AC-35: edit applies to the actual person/SA, never substituted owner."""
    from bisheng.app_runtime.domain.services import app_authorization_service, runtime_profile_service

    app = SimpleNamespace(id="app", tenant_id=3, owner_user_id=81)
    row = SimpleNamespace(kind="offline", state="verified", visibility="private", tenant_id=3, app_id="app")
    repo = SimpleNamespace(get_application=AsyncMock(return_value=app), get=AsyncMock(return_value=row))
    actor = SimpleNamespace(actor_kind=kind, actor_id=42, tenant_id=3)
    manifest = SimpleNamespace(delivery=SimpleNamespace(dependencies=SimpleNamespace(offline_artifacts=["artifact"])))
    authorize = AsyncMock()
    monkeypatch.setattr(app_authorization_service.AppAuthorizationService, "authorize_loaded_app", authorize)
    await runtime_profile_service.validate_offline_references(repo, "app", manifest, actor)
    authorize.assert_awaited_once_with(actor, app, "content_read")
    authorize.side_effect = PermissionDeniedError()
    with pytest.raises(PermissionDeniedError):
        await runtime_profile_service.validate_offline_references(repo, "app", manifest, actor)
    row.app_id = "another"
    authorize.reset_mock()
    with pytest.raises(AppNotOwnedBySubjectError):
        await runtime_profile_service.validate_offline_references(repo, "app", manifest, actor)
    authorize.assert_not_awaited()
