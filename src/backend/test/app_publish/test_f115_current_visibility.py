"""F115 current approval summary, AC-22 through AC-38 and AC-52."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def summary(monkeypatch):
    from bisheng.app_publish.domain.schemas.current_visibility import ApprovalVisibilityRead
    from bisheng.app_publish.domain.services import app_publish_current_visibility_service as module

    app = SimpleNamespace(id="app-a", tenant_id=60, owner_user_id=9, state="draft")
    runtime = SimpleNamespace(
        read_effective_action_sources=AsyncMock(return_value=()), check_action=AsyncMock(return_value=True)
    )
    adapter = SimpleNamespace(resolve_permission_target=AsyncMock(return_value=object()))
    directory = SimpleNamespace(describe_active_sources=AsyncMock(return_value=[]))
    monkeypatch.setattr(module, "read_application", AsyncMock(return_value=app))
    monkeypatch.setattr(module, "get_f048_runtime", AsyncMock(return_value=runtime))
    monkeypatch.setattr(module, "get_f048_resource_adapter", AsyncMock(return_value=adapter))
    monkeypatch.setattr(module, "get_grant_subject_directory", AsyncMock(return_value=directory))
    monkeypatch.setattr(
        module,
        "read_current_person_facts",
        AsyncMock(
            return_value={
                9: {
                    "id": 9,
                    "name": "Owner",
                    "state": "active",
                    "tenant_id": 60,
                    "token_version": 1,
                }
            }
        ),
    )
    monkeypatch.setattr(module, "is_tenant_admin", AsyncMock(return_value=False))
    monkeypatch.setattr(
        module.UserPayload,
        "init_login_user",
        AsyncMock(return_value=SimpleNamespace(user_id=9, tenant_id=60, is_global_super=False)),
    )
    context = ApprovalVisibilityRead(instance_id=1, tenant_id=60, app_id="app-a", viewer_user_id=2)
    viewer = SimpleNamespace(user_id=2, tenant_id=60, is_global_super=True)
    return module, context, viewer, runtime, directory, app


async def test_success_confirms_owner_only_without_granting_reader_management(summary):
    module, context, viewer, runtime, _, _ = summary
    result = await module.AppPublishCurrentVisibilityService.read(context, viewer)
    assert result["state"] == "available" and result["owner_only"] is True
    actor = runtime.check_action.call_args.args[0]
    assert actor.user_id == 9 and not actor.super_admin


async def test_multiple_userset_objects_are_current_and_typed(summary):
    module, context, viewer, _, directory, _ = summary
    directory.describe_active_sources.return_value = [
        {"type": "department", "id": "3", "name": "Dept", "include_children": True}
    ]
    result = await module.AppPublishCurrentVisibilityService.read(context, viewer)
    assert result["owner_only"] is False
    assert any(row["type"] == "department" for row in result["subjects"])


async def test_unavailable_directory_never_means_owner_only(summary):
    module, context, viewer, _, directory, _ = summary
    directory.describe_active_sources.side_effect = RuntimeError("test directory outage")
    result = await module.AppPublishCurrentVisibilityService.read(context, viewer)
    assert result["state"] == "unavailable" and result["owner_only"] is None
    assert result["subjects"] == [] and "directory outage" not in str(result)


async def test_deleted_app_keeps_no_current_authorization_claim(summary, monkeypatch):
    module, context, viewer, runtime, _, _ = summary
    monkeypatch.setattr(module, "read_application", AsyncMock(return_value=None))
    result = await module.AppPublishCurrentVisibilityService.read(context, viewer)
    assert result["state"] == "deleted" and result["owner_only"] is None
    runtime.read_effective_action_sources.assert_not_called()


async def test_foreign_application_is_refused_before_directory(summary):
    from bisheng.common.errcode.approval import ApprovalRequestPermissionDeniedError

    module, context, viewer, runtime, _, app = summary
    app.tenant_id = 61
    with pytest.raises(ApprovalRequestPermissionDeniedError):
        await module.AppPublishCurrentVisibilityService.read(context, viewer)
    runtime.read_effective_action_sources.assert_not_called()


async def test_foreign_deleted_row_does_not_bypass_tenant_binding(summary):
    from bisheng.common.errcode.approval import ApprovalRequestPermissionDeniedError

    module, context, viewer, runtime, _, app = summary
    app.tenant_id, app.state = 61, "deleted"
    with pytest.raises(ApprovalRequestPermissionDeniedError):
        await module.AppPublishCurrentVisibilityService.read(context, viewer)
    runtime.read_effective_action_sources.assert_not_called()


async def test_ineligible_owner_is_not_visible_even_if_name_remains(summary):
    module, context, viewer, runtime, _, _ = summary
    runtime.check_action.return_value = False
    result = await module.AppPublishCurrentVisibilityService.read(context, viewer)
    assert result["state"] == "available" and result["owner_only"] is False
    assert result["subjects"] == [] and result["owner"]["eligible"] is False


async def test_ordinary_approver_does_not_borrow_owner_or_admin_actor(summary):
    module, context, viewer, runtime, _, _ = summary
    viewer.is_global_super = False
    result = await module.AppPublishCurrentVisibilityService.read(context, viewer)
    assert result["state"] == "available"
    runtime.check_action.assert_awaited_once()
    assert runtime.check_action.call_args.args[0].user_id == 9


async def test_grant_edit_during_identity_read_refuses_partial_summary(summary):
    module, context, viewer, runtime, _, _ = summary
    runtime.read_effective_action_sources.side_effect = [(), (object(),)]
    result = await module.AppPublishCurrentVisibilityService.read(context, viewer)
    assert result["state"] == "unavailable" and result["owner_only"] is None
