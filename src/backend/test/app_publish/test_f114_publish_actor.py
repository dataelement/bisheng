"""Publishing another person's app is an action decision, never owner impersonation."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.permission import PermissionDeniedError


async def test_existing_publish_uses_real_principal_and_combined_actions(monkeypatch):
    from bisheng.app_publish.domain.services import publish_pipeline_service as mod

    principal = SimpleNamespace(actor_kind="service_account", actor_id=24, tenant_id=3, resource_owner_user_id=42)
    app = SimpleNamespace(id="target", tenant_id=3, owner_user_id=81)
    check = AsyncMock(return_value=app)
    monkeypatch.setattr(mod, "authorize_app", check)
    monkeypatch.setattr(mod.VersionService, "get_app_scoped", AsyncMock(return_value=app))
    result = await mod.PublishPipelineService._assert_authorized(app.id, principal, tenant_id=3)
    assert result.owner_user_id == 81
    assert check.await_args.args == (principal, app.id, "release_submit")
    check.side_effect = PermissionDeniedError()
    with pytest.raises(PermissionDeniedError):
        await mod.PublishPipelineService._assert_authorized(app.id, principal, tenant_id=3)
