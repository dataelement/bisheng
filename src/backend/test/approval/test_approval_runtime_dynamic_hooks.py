from __future__ import annotations

import inspect

import pytest

from bisheng.approval.domain.services.approval_center_service import ApprovalCenterService
from bisheng.approval.domain.services.approval_runtime_handler_factory import build_runtime_handler
from bisheng.bootstrap.approval_scenarios import bootstrap_approval_scenarios

F045_SCENARIO = "resource_user_invite_confirmation"
F046_SCENARIO = "knowledge_space_file_change_request"


@pytest.mark.parametrize("scenario_code", [F045_SCENARIO, F046_SCENARIO])
def test_new_business_scenarios_are_owned_by_policy_and_subscriber_registry(scenario_code: str) -> None:
    registry = bootstrap_approval_scenarios()

    assert registry.get_policy(scenario_code).scenario_code == scenario_code
    assert registry.get_subscriber(scenario_code).scenario_code == scenario_code
    assert registry.get_preset(scenario_code) is not None


@pytest.mark.parametrize("scenario_code", [F045_SCENARIO, F046_SCENARIO])
async def test_new_business_scenarios_have_no_runtime_handler(scenario_code: str) -> None:
    with pytest.raises(KeyError, match=scenario_code):
        await build_runtime_handler(scenario_code)


@pytest.mark.parametrize(
    ("scenario_code", "expected_class_name"),
    [
        ("menu_access_request", "MenuAccessApprovalHandler"),
        ("channel_subscribe_request", "ChannelSubscribeScenarioHandler"),
        ("knowledge_space_subscribe_request", "KnowledgeSpaceSubscribeScenarioHandler"),
    ],
)
async def test_three_online_scenarios_keep_runtime_handlers(
    scenario_code: str,
    expected_class_name: str,
) -> None:
    handler = await build_runtime_handler(scenario_code)

    assert type(handler).__name__ == expected_class_name


def test_approval_queries_do_not_scan_permission_or_knowledge_domains() -> None:
    for method in (
        ApprovalCenterService.list_my_tasks,
        ApprovalCenterService.list_my_requests,
        ApprovalCenterService.get_task_detail,
        ApprovalCenterService.get_instance_detail,
    ):
        source = inspect.getsource(method)
        assert "bisheng.permission" not in source
        assert "bisheng.knowledge" not in source
        assert "build_runtime_handler" not in source
