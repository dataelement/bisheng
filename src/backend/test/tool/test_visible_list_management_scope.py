"""Visible tool enumeration uses the selected tenant without conflicting aliases."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.permission.domain.services.data_scope import DATA_SCOPE_ALL, DATA_SCOPE_PERSONAL
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from bisheng.tool.domain.models.gpts_tools import GptsToolsType
from bisheng.tool.domain.services import tool as tool_service


@pytest.mark.parametrize("preset", [None, 0, 2])
@pytest.mark.parametrize(
    ("home_tenant", "target_tenant", "super_admin", "data_scope"),
    [
        (1, 60, True, DATA_SCOPE_ALL),
        (1, 60, True, DATA_SCOPE_PERSONAL),
        (60, 60, False, DATA_SCOPE_ALL),
        (1, 1, False, DATA_SCOPE_ALL),
    ],
)
async def test_visible_list_uses_selected_tenant_and_preserves_identity_and_filtering(
    monkeypatch, preset, home_tenant, target_tenant, super_admin, data_scope
):
    actor = PermissionActor(
        user_id=191,
        tenant_id=home_tenant,
        super_admin=super_admin,
        tenant_admin_tenant_ids=frozenset({home_tenant}),
        data_scope=data_scope,
    )
    user = UserPayload(user_id=191, tenant_id=home_tenant, user_role=[], is_global_super=super_admin)
    monkeypatch.setattr(tool_service, "get_current_tenant_id", lambda: target_tenant)
    monkeypatch.setattr(tool_service, "resolve_permission_actor", AsyncMock(return_value=actor))
    enumerate_visible = AsyncMock(return_value=SimpleNamespace(object_ids=("10", "20")))
    monkeypatch.setattr(
        tool_service,
        "get_f048_runtime",
        AsyncMock(return_value=SimpleNamespace(list_visible_objects=enumerate_visible)),
    )
    rows = [
        GptsToolsType(id=id_, tenant_id=target_tenant, user_id=191, name=f"Tool {id_}", is_preset=preset or 0)
        for id_ in (10, 20)
    ]
    load = AsyncMock(return_value=rows)
    monkeypatch.setattr(tool_service.GptsToolsDao, "aget_tenant_tool_type", load)
    monkeypatch.setattr(tool_service.GptsToolsDao, "aget_list_by_type", AsyncMock(return_value=[]))
    monkeypatch.setattr(tool_service.GptsToolsDao, "aget_preset_child_keys", AsyncMock(return_value={}))
    check = AsyncMock(return_value={"10": frozenset({"visible"}), "20": frozenset()})
    monkeypatch.setattr(tool_service, "batch_check_business_actions", check)

    result = await tool_service.ToolServices(login_user=user).get_tool_list(is_preset=preset, action="visible")

    assert [item.id for item in result] == [10]
    used_actor = enumerate_visible.await_args.args[0]
    assert used_actor.tenant_id == used_actor.current_tenant_id == target_tenant
    assert used_actor.subject_id == actor.subject_id
    assert used_actor.subject_type == actor.subject_type
    assert used_actor.super_admin is super_admin
    assert used_actor.tenant_admin_tenant_ids == actor.tenant_admin_tenant_ids
    assert used_actor.data_scope == data_scope
    assert actor.tenant_id == home_tenant
    assert user.tenant_id == home_tenant
    assert load.await_args.args == (target_tenant,)
    assert load.await_args.kwargs["tool_type_ids"] == [10, 20]
    check.assert_awaited_once()
    assert check.await_args.args[0] is user
    assert check.await_args.kwargs["actions"] == ("visible",)
