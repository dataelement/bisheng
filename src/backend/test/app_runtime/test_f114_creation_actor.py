"""Creation must retain the natural owner and grant the actual creator separately."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.permission.application.identity import PermissionActor


async def test_owner_projection_uses_actual_service_account(monkeypatch):
    from bisheng.app_runtime.domain.services import app_provision_service as mod

    actor = PermissionActor(subject_type="service_account", subject_id=24, tenant_id=3)
    record = SimpleNamespace(resource_id="target", owner_user_id=81, tenant_id=3)
    adapter = SimpleNamespace(build_creation_record=AsyncMock(return_value=record), authorize_created=AsyncMock())
    monkeypatch.setattr(mod, "get_f048_resource_adapter", AsyncMock(return_value=adapter))
    await mod.AppProvisionService._project_owner(app_id="target", owner_user_id=81, tenant_id=3, actor=actor)
    assert adapter.authorize_created.await_args.kwargs["actor"] is actor
    assert adapter.authorize_created.await_args.kwargs["record"].owner_user_id == 81


async def test_unknown_creation_rollback_preserves_orphan(monkeypatch):
    from bisheng.app_runtime.domain.services import app_provision_service as mod

    remove = AsyncMock()
    monkeypatch.setattr(mod.AppProvisionService, "_remove_orphan", remove)
    adapter = SimpleNamespace(
        build_creation_record=AsyncMock(return_value=SimpleNamespace()),
        rollback_created=AsyncMock(side_effect=RuntimeError("unknown")),
    )
    monkeypatch.setattr(mod, "get_f048_resource_adapter", AsyncMock(return_value=adapter))
    with pytest.raises(RuntimeError, match="unknown"):
        await mod.AppProvisionService._rollback_owner("target", PermissionActor(subject_id=42, tenant_id=3))
    remove.assert_not_awaited()
