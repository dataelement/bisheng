"""Tool/Skill admission uses the existing visibility facade. AC-78/79/82/83."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.open_api import PersonalTokenDataScopeError
from bisheng.common.errcode.permission import PermissionInvalidResourceError
from bisheng.linsight.domain.services.skill_permission import SkillPermissionAdapter
from bisheng.permission.application import business_authorization as business
from bisheng.permission.application.identity import reset_current_permission_actor, set_current_permission_actor
from bisheng.permission.application.resource_authorization import ResourceAuthorizationRegistry
from bisheng.permission.domain.services.permission_action_service import F048PermissionService, PermissionActor
from bisheng.tool.domain.services.f048_tool_permission import F048ToolPermissionAdapter, ToolPermissionRecord


@pytest.fixture
def admission(monkeypatch):
    fga = SimpleNamespace(check=AsyncMock(return_value=True))
    runtime = F048PermissionService(
        catalog=SimpleNamespace(
            ensure_runtime_ready=AsyncMock(),
            effective_actions=AsyncMock(return_value=("use", "edit", "delete")),
        ),
        scope_fence=SimpleNamespace(ensure_readable=AsyncMock(return_value=False)),
        marker=SimpleNamespace(consistency_for=AsyncMock(return_value=None)),
        fga=fga,
        list_policy=SimpleNamespace(),
    )
    records = {
        str(number): ToolPermissionRecord(
            tenant_id=101,
            resource_id=str(number),
            status="ACTIVE",
            owner_user_id=None if preset else 7,
            permission_version=1,
            context_version="tool-context",
            preset=preset,
        )
        for number, preset in ((10, False), (20, True))
    }
    tool = F048ToolPermissionAdapter(
        loader=SimpleNamespace(load_permission_record=AsyncMock(side_effect=records.get)), permission=runtime
    )
    skill = SkillPermissionAdapter(
        SimpleNamespace(get_permission_version=AsyncMock(return_value=(1, "skill-context"))),
        SimpleNamespace(
            get=AsyncMock(
                return_value=SimpleNamespace(
                    id=30, tenant_id=101, owner_user_id=0, source="builtin", enabled=True, update_time=None
                )
            )
        ),
    )
    registry = ResourceAuthorizationRegistry()
    registry.register("tool", tool)
    registry.register("linsight_skill", skill)
    monkeypatch.setattr(business, "get_f048_resource_registry", AsyncMock(return_value=registry))
    monkeypatch.setattr(business, "get_f048_runtime", AsyncMock(return_value=runtime))
    token = set_current_permission_actor(None)
    try:
        yield SimpleNamespace(fga=fga, runtime=runtime, tool=tool, records=records)
    finally:
        reset_current_permission_actor(token)


@pytest.mark.parametrize("resource_type,resource_id", [("tool", 10), ("tool", 20), ("linsight_skill", 30)])
@pytest.mark.parametrize("subject_type", ["user", "service_account"])
@pytest.mark.parametrize("action", ["visible", "use"])
async def test_visible_only_admission_keeps_original_actor(admission, resource_type, resource_id, subject_type, action):
    actor = PermissionActor(subject_type=subject_type, subject_id=7, tenant_id=101)
    token = set_current_permission_actor(actor)
    try:
        assert await business.check_business_action(
            object(), resource_type=resource_type, resource_id=resource_id, action=action
        )
    finally:
        reset_current_permission_actor(token)
    assert admission.fga.check.await_args.kwargs["user"] == actor.fga_subject
    assert admission.fga.check.await_args.kwargs["relation"] == "visible"
    assert "use" not in await admission.runtime.effective_actions(resource_type)


@pytest.mark.parametrize("resource_type,resource_id", [("tool", 10), ("tool", 20), ("linsight_skill", 30)])
async def test_visibility_denial_has_no_use_fallback(admission, resource_type, resource_id):
    admission.fga.check.return_value = False
    token = set_current_permission_actor(PermissionActor(user_id=7, tenant_id=101))
    try:
        assert not await business.check_business_action(
            object(), resource_type=resource_type, resource_id=resource_id, action="use"
        )
    finally:
        reset_current_permission_actor(token)
    admission.fga.check.assert_awaited_once()


@pytest.mark.parametrize("resource_type,resource_id", [("tool", 10), ("tool", 20), ("linsight_skill", 30)])
async def test_original_narrowed_actor_cannot_fall_back_to_user_identity(
    admission, monkeypatch, resource_type, resource_id
):
    monkeypatch.setattr(
        "bisheng.permission.domain.services.permission_action_service.get_data_scope_resolver", lambda: None
    )
    token = set_current_permission_actor(PermissionActor(user_id=7, tenant_id=101, data_scope="OWNED"))
    try:
        with pytest.raises(PersonalTokenDataScopeError):
            await business.check_business_action(
                object(), resource_type=resource_type, resource_id=resource_id, action="use"
            )
    finally:
        reset_current_permission_actor(token)
    admission.fga.check.assert_not_awaited()


@pytest.mark.parametrize("resource_type,resource_id", [("tool", 10), ("tool", 20), ("linsight_skill", 30)])
async def test_business_tenant_guard_still_rejects(admission, resource_type, resource_id):
    token = set_current_permission_actor(PermissionActor(user_id=7, tenant_id=202))
    try:
        with pytest.raises(PermissionInvalidResourceError):
            await business.check_business_action(
                object(), resource_type=resource_type, resource_id=resource_id, action="visible"
            )
    finally:
        reset_current_permission_actor(token)
    admission.fga.check.assert_not_awaited()


async def test_preset_creation_emits_only_visibility(admission):
    permission = SimpleNamespace(authorize_system_owned=AsyncMock())
    adapter = F048ToolPermissionAdapter(loader=object(), permission=permission)
    await adapter.authorize_created(record=admission.records["20"], actor=PermissionActor(user_id=7, tenant_id=101))
    assert permission.authorize_system_owned.await_args.kwargs["action_codes"] == ("visible",)
