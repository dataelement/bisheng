"""Runtime records and retained export artifacts recheck application edit."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.permission import PermissionDeniedError


async def test_selected_app_audit_uses_edit_and_concrete_tenant(monkeypatch):
    from bisheng.app_governance.domain.repositories.runtime_audit_repository import RuntimeAuditRepository
    from bisheng.app_governance.domain.services import runtime_audit_scope as mod

    user = UserPayload(user_id=42, tenant_id=3, user_role=[], token_version=7)
    monkeypatch.setattr(
        RuntimeAuditRepository, "current_user", AsyncMock(return_value=SimpleNamespace(token_version=7))
    )
    monkeypatch.setattr(UserPayload, "init_login_user", AsyncMock(return_value=user))
    monkeypatch.setattr(mod, "get_current_tenant_id", lambda: 3)
    monkeypatch.setattr(mod, "resolve_management_scope", AsyncMock(return_value=SimpleNamespace(tenant_id=3)))
    auth = AsyncMock()
    monkeypatch.setattr(mod, "authorize_app", auth)
    scope = await mod.resolve_scope(user, app_id="target")
    assert scope.tenant_id == 3
    assert scope.authorized_app_ids == ("target",)
    assert auth.await_args.args == (user, "target", "audit_read")
    auth.side_effect = PermissionDeniedError()
    with pytest.raises(PermissionDeniedError):
        await mod.resolve_scope(user, app_id="target")


async def test_export_download_rechecks_selected_app(monkeypatch):
    from bisheng.app_governance.domain.schemas.runtime_audit import AuthorizedRuntimeAuditScope
    from bisheng.app_governance.domain.services import runtime_audit_export_service as mod

    monkeypatch.setattr(mod, "enabled", lambda: None)
    job = SimpleNamespace(
        creator_user_id=42,
        tenant_id=3,
        scope_tenant_id=3,
        normalized_filter={"app_id": "target", "authorized_app_ids": ["target"]},
    )
    repo = SimpleNamespace(get=AsyncMock(return_value=job))
    resolver = AsyncMock(return_value=AuthorizedRuntimeAuditScope(42, 3, 3, ("target",)))
    service = mod.RuntimeAuditExportService(repository=repo, scope_resolver=resolver)
    assert await service.authorized_job(SimpleNamespace(user_id=42, tenant_id=3), "job") is job
    assert resolver.await_args.kwargs["app_id"] == "target"
    resolver.side_effect = PermissionDeniedError()
    with pytest.raises(PermissionDeniedError):
        await service.authorized_job(SimpleNamespace(user_id=42, tenant_id=3), "job")
