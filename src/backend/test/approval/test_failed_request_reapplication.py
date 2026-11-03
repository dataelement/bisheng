"""A failed business execution must never masquerade as a new pending approval."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.approval.application.request_state import get_failed_request_keys
from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository
from bisheng.approval.domain.schemas.approval_center_schema import ApprovalGateRequest
from bisheng.approval.domain.services.approval_gate import ApprovalGate
from bisheng.common.errcode.approval import ApprovalExecutionFailedError

SCENARIOS = [
    "knowledge_space_subscribe_request",
    "channel_subscribe_request",
    "menu_access_request",
    "app_publish_request",
]


@pytest.mark.parametrize("scenario", SCENARIOS)
async def test_failed_reapplication_reports_recovery_required_without_new_work(scenario):
    repository = SimpleNamespace(
        find_duplicate_active_instance=AsyncMock(return_value=SimpleNamespace(id=16, status="execute_failed")),
        create_instance=AsyncMock(),
        create_task=AsyncMock(),
        create_outbox=AsyncMock(),
    )
    registry = SimpleNamespace(get_handler=AsyncMock())
    gate = ApprovalGate(registry=registry, instance_repository=repository)
    with pytest.raises(ApprovalExecutionFailedError) as raised:
        await gate.request_or_pass(
            ApprovalGateRequest(
                tenant_id=1,
                scenario_code=scenario,
                business_key="resource:77:user:10",
                business_resource_type="resource",
                business_resource_id="77",
                business_name="resource",
                applicant_user_id=10,
                applicant_user_name="applicant",
            )
        )
    assert raised.value.code == 18120
    repository.create_instance.assert_not_awaited()
    repository.create_task.assert_not_awaited()
    repository.create_outbox.assert_not_awaited()
    registry.get_handler.assert_not_awaited()


@pytest.mark.parametrize("status,expected", [("pending", "pending"), ("exception", "exception")])
async def test_existing_waiting_or_exception_request_still_deduplicates(status, expected):
    gate = ApprovalGate(
        registry=SimpleNamespace(get_handler=AsyncMock()),
        instance_repository=SimpleNamespace(
            find_duplicate_active_instance=AsyncMock(return_value=SimpleNamespace(id=13, status=status))
        ),
    )
    result = await gate.request_or_pass(
        ApprovalGateRequest(
            tenant_id=1,
            scenario_code=SCENARIOS[0],
            business_key="space:77:user:10",
            business_resource_type="knowledge_space",
            business_resource_id="77",
            business_name="space",
            applicant_user_id=10,
            applicant_user_name="applicant",
        )
    )
    assert result.decision == expected
    assert result.instance_id == 13


async def test_pending_request_wins_over_older_failed_execution(monkeypatch):
    rows = [
        SimpleNamespace(business_key="space:77:user:10", status="pending"),
        SimpleNamespace(business_key="space:77:user:10", status="execute_failed"),
        SimpleNamespace(business_key="space:78:user:10", status="execute_failed"),
    ]
    monkeypatch.setattr(
        ApprovalInstanceRepository, "list_active_instances_for_business_keys", AsyncMock(return_value=rows)
    )
    assert await get_failed_request_keys(
        tenant_id=1,
        scenario_code=SCENARIOS[0],
        applicant_user_id=10,
        business_keys=["space:77:user:10", "space:78:user:10"],
    ) == frozenset({"space:78:user:10"})


async def test_empty_and_large_request_batches(monkeypatch):
    lookup = AsyncMock(return_value=[])
    monkeypatch.setattr(ApprovalInstanceRepository, "list_active_instances_for_business_keys", lookup)
    assert (
        await get_failed_request_keys(tenant_id=1, scenario_code=SCENARIOS[0], applicant_user_id=10, business_keys=[])
        == frozenset()
    )
    lookup.assert_not_awaited()
    keys = [f"space:{i}:user:10" for i in range(205)]
    assert (
        await get_failed_request_keys(
            tenant_id=1, scenario_code=SCENARIOS[0], applicant_user_id=10, business_keys=keys + keys
        )
        == frozenset()
    )
    assert [len(call.kwargs["business_keys"]) for call in lookup.await_args_list] == [100, 100, 5]
