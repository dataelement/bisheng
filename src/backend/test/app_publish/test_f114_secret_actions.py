"""F114 edit manages configuration; applying it additionally requires publish."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.permission.application.identity import PermissionActor


@pytest.fixture
def secret_policy(monkeypatch):
    from bisheng.app_runtime.domain.services import app_authorization_service as mod

    app = SimpleNamespace(id="target", tenant_id=2, owner_user_id=81, state="online")
    actor = SimpleNamespace(user_id=42, tenant_id=2, is_global_super=False)
    allowed = set()
    monkeypatch.setattr(
        mod.AppAuthorizationService,
        "resolve_actor",
        AsyncMock(return_value=PermissionActor(subject_id=42, tenant_id=2)),
    )
    monkeypatch.setattr(mod, "check_business_action", AsyncMock(side_effect=lambda *a, **kw: kw["action"] in allowed))
    monkeypatch.setattr(mod.AppAuthorizationService, "load_app", AsyncMock(return_value=app))
    return app, actor, allowed


async def test_non_owner_editor_can_manage_values(secret_policy):
    from bisheng.app_publish.domain.services.app_secret_service import AppSecretService

    app, actor, allowed = secret_policy
    allowed.add("edit")
    await AppSecretService._require_editor(app, actor)
    allowed.clear()
    allowed.add("publish")
    with pytest.raises(PermissionDeniedError):
        await AppSecretService._require_editor(app, actor)


@pytest.mark.parametrize("permissions", [{"edit"}, {"publish"}, {"edit", "publish"}])
async def test_confirmed_rebuild_is_combined(secret_policy, permissions):
    from bisheng.app_runtime.domain.services.secret_rebuild_service import AppSecretRebuildService

    app, actor, allowed = secret_policy
    allowed.update(permissions)
    if permissions == {"edit", "publish"}:
        await AppSecretRebuildService._require_rebuild(app, actor)
    else:
        with pytest.raises(PermissionDeniedError):
            await AppSecretRebuildService._require_rebuild(app, actor)
