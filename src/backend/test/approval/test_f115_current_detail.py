"""F115 AC-22/30/31/32/33/34/35/36/37/38/52: decoration follows qualification."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def detail(monkeypatch):
    from bisheng.approval.domain.services import approval_center_service as module

    instance = SimpleNamespace(
        id=1,
        tenant_id=60,
        scenario_code="app_publish_request",
        scenario_name="Publish",
        business_name="App",
        applicant_user_id=9,
        applicant_user_name="Owner",
        applicant_department_id=None,
        flow_version_id=None,
        status="pending",
        current_node_name=None,
        detail_snapshot={"version_no": 1, "visibility_snapshot": []},
        payload_snapshot={"app_id": "app-a"},
        reason=None,
        create_time=None,
        update_time=None,
    )
    task = SimpleNamespace(
        id=2, instance_id=1, approver_user_id=3, status="pending", node_name="Review", comment=None, update_time=None
    )
    repository = module.ApprovalInstanceRepository
    for method, value in (("get_task", task), ("get_instance", instance), ("list_tasks", []), ("list_action_logs", [])):
        monkeypatch.setattr(repository, method, AsyncMock(return_value=value))
    current = AsyncMock(return_value={"current_visibility": {"state": "available", "owner_only": True}})
    monkeypatch.setattr(module, "read_current_scenario_detail", current)
    viewer = SimpleNamespace(user_id=3, tenant_id=60, is_admin=lambda: False)
    return module, instance, viewer, current


async def test_authorized_task_gets_current_decoration_without_changing_snapshot(detail):
    module, instance, viewer, current = detail
    frozen = deepcopy(instance.detail_snapshot)
    result = await module.ApprovalCenterService.get_task_detail(task_id=2, login_user=viewer)
    assert result["current_visibility"]["owner_only"] is True
    assert result["detail_snapshot"] == frozen == instance.detail_snapshot
    current.assert_awaited_once()


async def test_tenant_denial_precedes_current_scope_read(detail):
    from bisheng.common.errcode.approval import ApprovalRequestPermissionDeniedError

    module, _, viewer, current = detail
    viewer.tenant_id = 61
    with pytest.raises(ApprovalRequestPermissionDeniedError):
        await module.ApprovalCenterService.get_task_detail(task_id=2, login_user=viewer)
    current.assert_not_called()


async def test_personal_instance_uses_same_current_decoration(detail):
    module, _, viewer, current = detail
    viewer.user_id = 9
    result = await module.ApprovalCenterService.get_instance_detail(instance_id=1, login_user=viewer)
    assert result["current_visibility"]["state"] == "available"
    assert current.call_args.kwargs["management"] is False


async def test_management_reader_can_read_current_scope_without_app_management(detail, monkeypatch):
    from bisheng.permission import application

    module, _, viewer, current = detail
    monkeypatch.setattr(application, "is_tenant_admin", AsyncMock(return_value=True))
    result = await module.ApprovalCenterService.get_instance_detail(instance_id=1, login_user=viewer, management=True)
    assert result["current_visibility"]["state"] == "available"
    assert current.call_args.kwargs["management"] is True


async def test_nonparticipant_instance_never_queries_current_roster(detail):
    from bisheng.common.errcode.approval import ApprovalRequestPermissionDeniedError

    module, _, viewer, current = detail
    with pytest.raises(ApprovalRequestPermissionDeniedError):
        await module.ApprovalCenterService.get_instance_detail(instance_id=1, login_user=viewer)
    current.assert_not_called()


@pytest.mark.parametrize(
    "scenario", ["menu_access_request", "channel_subscribe_request", "knowledge_space_subscribe_request"]
)
async def test_other_scenarios_do_not_create_dynamic_queries(scenario, monkeypatch):
    from bisheng.approval.domain.services import approval_runtime_handler_factory as factory

    builder = AsyncMock()
    monkeypatch.setattr(factory, "build_runtime_handler", builder)
    result = await factory.read_current_scenario_detail(SimpleNamespace(scenario_code=scenario), object())
    assert result == {}
    builder.assert_not_called()
