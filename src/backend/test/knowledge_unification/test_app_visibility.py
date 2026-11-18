"""T135: current visible recipients do not confer application management.

Use the production summary and action policy with external permission and
identity ports replaced; no FGA, database, broker, or model calls are needed.
"""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.app_runtime.domain.schemas.app_authorization import APP_ACTIONS, MANAGEMENT_ACTIONS, required_actions
from bisheng.common.errcode.app_factory import AppNotFoundError
from bisheng.common.errcode.approval import ApprovalRequestPermissionDeniedError
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.permission.application.identity import PermissionActor


@pytest.fixture
def current_summary(monkeypatch):
    from bisheng.app_publish.domain.schemas.current_visibility import ApprovalVisibilityRead
    from bisheng.app_publish.domain.services import app_publish_current_visibility_service as module

    app = SimpleNamespace(id="app-a", tenant_id=101, owner_user_id=9, state="draft")
    target = object()
    runtime = SimpleNamespace(
        read_effective_action_sources=AsyncMock(return_value=("visible-source",)),
        check_action=AsyncMock(side_effect=lambda actor, target, action: action == "visible"),
    )
    adapter = SimpleNamespace(resolve_permission_target=AsyncMock(return_value=target))
    directory = SimpleNamespace(
        describe_active_sources=AsyncMock(
            return_value=[{"type": "department", "id": "3", "name": "Department", "include_children": True}]
        )
    )
    monkeypatch.setattr(module, "read_application", AsyncMock(return_value=app))
    monkeypatch.setattr(module, "get_f048_runtime", AsyncMock(return_value=runtime))
    monkeypatch.setattr(module, "get_f048_resource_adapter", AsyncMock(return_value=adapter))
    monkeypatch.setattr(module, "get_grant_subject_directory", AsyncMock(return_value=directory))
    monkeypatch.setattr(module, "is_tenant_admin", AsyncMock(return_value=False))
    monkeypatch.setattr(
        module,
        "read_current_person_facts",
        AsyncMock(
            return_value={9: {"id": 9, "name": "Owner", "state": "active", "tenant_id": 101, "token_version": 1}}
        ),
    )
    monkeypatch.setattr(
        module.UserPayload,
        "init_login_user",
        AsyncMock(return_value=SimpleNamespace(user_id=9, tenant_id=101, is_global_super=False)),
    )
    viewer = SimpleNamespace(user_id=2, tenant_id=101, is_global_super=False)
    context = ApprovalVisibilityRead(instance_id=1, tenant_id=101, app_id=app.id, viewer_user_id=viewer.user_id)
    return SimpleNamespace(
        module=module,
        app=app,
        target=target,
        runtime=runtime,
        adapter=adapter,
        directory=directory,
        viewer=viewer,
        context=context,
    )


async def test_summary_reads_current_visible_sources_and_exact_owner(current_summary):
    case = current_summary
    result = await case.module.AppPublishCurrentVisibilityService.read(case.context, case.viewer)

    assert result["state"] == "available"
    assert result["owner"] == {"id": "9", "name": "Owner", "eligible": True}
    assert result["owner_only"] is False
    assert result["subjects"][0] == {"type": "user", "id": "9", "name": "Owner"}
    target_call = case.adapter.resolve_permission_target.await_args.kwargs
    assert target_call["action"] == "visible" and target_call["actor"].user_id == case.viewer.user_id
    assert case.runtime.read_effective_action_sources.await_count == 2
    assert all(
        call.kwargs == {"target": case.target, "action": "visible"}
        for call in case.runtime.read_effective_action_sources.await_args_list
    )
    owner_call = case.runtime.check_action.await_args.args
    assert owner_call[0].user_id == 9 and not owner_call[0].super_admin
    assert owner_call[1:] == (case.target, "visible")


async def test_changed_visible_sources_do_not_claim_a_partial_current_scope(current_summary):
    case = current_summary
    case.runtime.read_effective_action_sources.side_effect = [("old",), ("new",)]
    result = await case.module.AppPublishCurrentVisibilityService.read(case.context, case.viewer)
    assert result["state"] == "unavailable" and result["owner_only"] is None
    assert result["subjects"] == []


async def test_failed_optional_current_read_keeps_truthful_unavailable_state(current_summary):
    case = current_summary
    case.directory.describe_active_sources.side_effect = RuntimeError("private directory failure")
    result = await case.module.AppPublishCurrentVisibilityService.read(case.context, case.viewer)
    assert result["state"] == "unavailable" and result["owner_only"] is None
    assert "private directory failure" not in str(result)


@pytest.mark.parametrize("change", ["viewer", "tenant", "payload"])
async def test_current_summary_keeps_original_approval_read_qualification(current_summary, change):
    case = current_summary
    if change == "viewer":
        case.viewer.user_id = 3
    elif change == "tenant":
        case.app.tenant_id = 202
    else:
        case.context = replace(case.context, payload_app_id="other")
    with pytest.raises(ApprovalRequestPermissionDeniedError):
        await case.module.AppPublishCurrentVisibilityService.read(case.context, case.viewer)
    case.runtime.read_effective_action_sources.assert_not_awaited()


@pytest.fixture
def app_policy(monkeypatch):
    from bisheng.app_runtime.domain.services import app_authorization_service as module

    app = SimpleNamespace(id="app-a", tenant_id=101, owner_user_id=9, state="stopped")
    actor = PermissionActor(subject_type="user", subject_id=2, tenant_id=101)
    checker = AsyncMock(side_effect=lambda *args, **kwargs: kwargs["action"] == "visible")
    batch = AsyncMock()
    monkeypatch.setattr(module.AppAuthorizationService, "resolve_actor", AsyncMock(return_value=actor))
    monkeypatch.setattr(module, "check_business_action", checker)
    monkeypatch.setattr(module, "batch_check_business_actions", batch)
    return SimpleNamespace(module=module, app=app, actor=actor, checker=checker, batch=batch)


def test_canonical_app_actions_retire_use_without_adding_management_authority():
    assert APP_ACTIONS == ("visible", "edit", "manage_permission", "delete", "publish", "unpublish")
    assert MANAGEMENT_ACTIONS == frozenset({"edit", "manage_permission", "delete", "publish", "unpublish"})
    assert required_actions("release_submit") == ("edit", "publish")
    assert required_actions("approved_start") == ("publish",)
    assert required_actions("restore", resume=True) == ("edit", "publish")


@pytest.mark.parametrize("operation", ["management_read", "release_submit", "approved_start", "grant_manage", "share"])
async def test_visible_only_never_grants_management_publish_or_share(app_policy, operation):
    case = app_policy
    with pytest.raises(PermissionDeniedError):
        await case.module.AppAuthorizationService.authorize_loaded_app(case.actor, case.app, operation)
    assert all(call.kwargs["action"] not in {"visible", "use"} for call in case.checker.await_args_list)


async def test_management_dto_requests_visible_and_retains_only_managed_apps(app_policy):
    case = app_policy
    other = SimpleNamespace(id="visible-only", tenant_id=101, owner_user_id=8, state="online")
    case.batch.return_value = {case.app.id: frozenset({"visible", "edit"}), other.id: frozenset({"visible"})}
    result = await case.module.AppAuthorizationService.management_actions(case.actor, [case.app, other])
    assert result == {case.app.id: frozenset({"visible", "edit"})}
    assert case.batch.await_args.args[0] is case.actor
    assert case.batch.await_args.kwargs["actions"] == (
        "visible",
        "edit",
        "manage_permission",
        "delete",
        "publish",
        "unpublish",
    )


@pytest.mark.parametrize("state,tenant", [("deleted", 101), ("online", 202)])
async def test_visible_result_does_not_bypass_app_lifecycle_or_tenant(app_policy, state, tenant):
    case = app_policy
    case.app.state, case.app.tenant_id = state, tenant
    with pytest.raises(AppNotFoundError):
        await case.module.AppAuthorizationService.authorize_loaded_app(case.actor, case.app, "approved_start")
    case.checker.assert_not_awaited()
