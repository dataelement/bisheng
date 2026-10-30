"""Granted management access must agree with the managed application list."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.app_publish.domain.services.publish_status_service import PublishStatusService
from bisheng.app_runtime.domain.services.app_query_service import AppQueryService
from bisheng.common.errcode.app_factory import AppManageForbiddenError, AppNotFoundError
from bisheng.common.errcode.app_publish import AppPublishOwnerOnlyError


@pytest.mark.parametrize("allowed", [True, False])
async def test_detail_and_publish_status_use_concrete_edit_action(monkeypatch, allowed):
    app = SimpleNamespace(id="app", tenant_id=2, owner_user_id=10)
    actor = SimpleNamespace(user_id=11, tenant_id=2, is_global_super=False)
    monkeypatch.setattr(AppQueryService, "_load", AsyncMock(return_value=app))
    monkeypatch.setattr(
        "bisheng.app_runtime.domain.services.app_query_service.check_tenant_admin", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(
        "bisheng.app_publish.domain.services.publish_status_service.check_tenant_admin", AsyncMock(return_value=False)
    )
    check = AsyncMock(return_value=allowed)
    monkeypatch.setattr("bisheng.permission.application.business_authorization.check_business_action", check)
    if allowed:
        assert await AppQueryService._load_visible("app", actor) is app
        await PublishStatusService._require_viewer(app, actor)
    else:
        with pytest.raises(AppManageForbiddenError):
            await AppQueryService._load_visible("app", actor)
        with pytest.raises(AppPublishOwnerOnlyError):
            await PublishStatusService._require_viewer(app, actor)
    assert check.await_count == 2
    assert check.call_args.kwargs == {"resource_type": "app", "resource_id": "app", "action": "edit"}


async def test_cross_tenant_and_developer_key_do_not_gain_access(monkeypatch):
    app = SimpleNamespace(id="app", tenant_id=2, owner_user_id=10)
    actor = SimpleNamespace(user_id=11, tenant_id=3, is_global_super=False)
    monkeypatch.setattr(AppQueryService, "_load", AsyncMock(return_value=app))
    check = AsyncMock(return_value=True)
    monkeypatch.setattr("bisheng.permission.application.business_authorization.check_business_action", check)
    with pytest.raises(AppNotFoundError):
        await AppQueryService._load_visible("app", actor)
    actor.tenant_id = 2
    with pytest.raises(AppNotFoundError):
        await AppQueryService._load_visible("app", actor, entry="cli")
    with pytest.raises(AppPublishOwnerOnlyError):
        await PublishStatusService._require_viewer(app, actor, entry="mcp")
    check.assert_not_called()
