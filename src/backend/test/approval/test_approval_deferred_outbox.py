from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

import bisheng.approval.domain.services.approval_center_service as approval_center_module
import bisheng.approval.domain.services.approval_outbox_service as outbox_service_module
from bisheng.approval.domain.models.approval_instance import (
    ApprovalInstance,
    ApprovalInstanceStatus,
    ApprovalOutbox,
    ApprovalOutboxStatus,
)
from bisheng.approval.domain.ports.scenario_policy import DECISION_DELIVERY_COMPLETION_MODE
from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository
from bisheng.approval.domain.services.approval_center_service import ApprovalCenterService
from bisheng.approval.domain.services.approval_exception_service import ApprovalExceptionService
from bisheng.approval.domain.services.approval_outbox_service import ApprovalOutboxService

TENANT_ID = 42
DECISION_DELIVERY_SCENARIOS = (
    "resource_user_invite_confirmation",
    "knowledge_space_file_change_request",
)
LEGACY_SCENARIOS = (
    "menu_access_request",
    "channel_subscribe_request",
    "knowledge_space_subscribe_request",
)


def _instance(*, scenario_code: str, status: str = ApprovalInstanceStatus.APPROVED) -> ApprovalInstance:
    return ApprovalInstance(
        id=31,
        tenant_id=TENANT_ID,
        scenario_code=scenario_code,
        scenario_name=scenario_code,
        handler_key=scenario_code,
        business_key=f"{scenario_code}:request:41",
        business_resource_type="test_request",
        business_resource_id="41",
        business_name="request",
        applicant_user_id=7,
        applicant_user_name="applicant",
        status=status,
        payload_snapshot={"request_id": 41},
        detail_snapshot={},
    )


@dataclass
class _LegacyOutboxRepository:
    scenario_code: str
    outbox: ApprovalOutbox = field(init=False)
    instance: ApprovalInstance = field(init=False)
    failure_exception_types: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.instance = _instance(scenario_code=self.scenario_code)
        self.outbox = ApprovalOutbox(
            id=11,
            tenant_id=TENANT_ID,
            instance_id=int(self.instance.id),
            handler_key=self.scenario_code,
            status=ApprovalOutboxStatus.PENDING,
            payload_snapshot={"request_id": 41},
        )

    async def get_outbox(self, outbox_id: int) -> ApprovalOutbox | None:
        return self.outbox if outbox_id == self.outbox.id else None

    async def claim_outbox(self, *, outbox_id: int, claim_ttl_seconds: int) -> ApprovalOutbox | None:
        del claim_ttl_seconds
        if outbox_id != self.outbox.id:
            return None
        self.outbox.update_time = datetime.utcnow()
        self.instance.status = ApprovalInstanceStatus.EXECUTING
        return self.outbox

    async def finalize_outbox_success(self, *, outbox_id: int, expected_claimed_at: datetime | None = None):
        assert outbox_id == self.outbox.id
        assert expected_claimed_at == self.outbox.update_time
        self.outbox.status = ApprovalOutboxStatus.SUCCESS
        self.instance.status = ApprovalInstanceStatus.EXECUTED
        return self.outbox, self.instance

    async def finalize_outbox_failure(
        self,
        *,
        outbox_id: int,
        error_summary: str | None,
        expected_claimed_at: datetime | None = None,
    ):
        assert outbox_id == self.outbox.id
        assert expected_claimed_at == self.outbox.update_time
        self.outbox.status = ApprovalOutboxStatus.FAILED
        self.outbox.error_summary = error_summary
        self.instance.status = ApprovalInstanceStatus.EXECUTE_FAILED
        self.failure_exception_types.append("execute_failed")
        return self.outbox, self.instance


@pytest.mark.parametrize("scenario_code", LEGACY_SCENARIOS)
@pytest.mark.parametrize("success", [True, False])
async def test_three_released_scenarios_keep_synchronous_handler_success_and_failure(
    scenario_code: str,
    success: bool,
) -> None:
    repository = _LegacyOutboxRepository(scenario_code)
    service = ApprovalOutboxService(instance_repository=repository)
    executor = AsyncMock(return_value=(success, None if success else "controlled handler failure"))

    with (
        patch.object(service, "_write_handler_audit_log", new=AsyncMock()),
        patch(
            "bisheng.approval.domain.services.approval_notification_service.ApprovalNotificationService.notify_admins",
            new=AsyncMock(),
        ),
    ):
        result = await service.execute_outbox(outbox_id=11, executor=executor)

    executor.assert_awaited_once_with(repository.outbox)
    assert result is success
    if success:
        assert repository.outbox.status == ApprovalOutboxStatus.SUCCESS
        assert repository.instance.status == ApprovalInstanceStatus.EXECUTED
        assert repository.failure_exception_types == []
    else:
        assert repository.outbox.status == ApprovalOutboxStatus.FAILED
        assert repository.instance.status == ApprovalInstanceStatus.EXECUTE_FAILED
        assert repository.failure_exception_types == ["execute_failed"]


@pytest.mark.parametrize("scenario_code", DECISION_DELIVERY_SCENARIOS)
async def test_f045_f046_finalize_only_approval_terminal_fact_and_decision_event(
    scenario_code: str,
) -> None:
    instance = _instance(scenario_code=scenario_code)
    instance.handler_key = f"{scenario_code}_subscriber"
    instance.payload_snapshot = {
        "completion_mode": DECISION_DELIVERY_COMPLETION_MODE,
        "business_request_type": instance.business_resource_type,
        "business_request_id": instance.business_resource_id,
        "request_fingerprint": f"fingerprint:{scenario_code}",
    }
    session = SimpleNamespace(add=Mock(), flush=AsyncMock())
    service = ApprovalCenterService(instance_repository=ApprovalInstanceRepository)
    effects = approval_center_module._DecisionPostCommitEffects()

    with patch.object(
        ApprovalInstanceRepository,
        "create_terminal_decision_event_in_session",
        new=AsyncMock(),
    ) as create_decision_event:
        legacy_outbox = await service._finalize_instance_locked(
            session=session,
            instance=instance,
            operator_user_id=9,
            post_commit_effects=effects,
        )

    assert legacy_outbox is None
    assert instance.status == ApprovalInstanceStatus.APPROVED
    assert instance.status not in {
        ApprovalInstanceStatus.EXECUTING,
        ApprovalInstanceStatus.EXECUTED,
        ApprovalInstanceStatus.EXECUTE_FAILED,
    }
    create_decision_event.assert_awaited_once_with(
        session,
        instance=instance,
        decision="approved",
        operator_user_id=9,
    )
    assert all(not isinstance(call.args[0], ApprovalOutbox) for call in session.add.call_args_list)


def test_legacy_outbox_contract_has_no_unreleased_deferred_extension() -> None:
    forbidden_statuses = {"PROCESSING", "DEFERRED"}
    forbidden_fields = {"execution_token", "deferred_deadline", "heartbeat_at"}
    forbidden_symbols = {
        "Deferred",
        "defer_execution",
        "heartbeat_deferred_execution",
        "complete_deferred_execution",
        "complete_deferred_execution_in_uow",
        "require_deferred_execution_in_uow",
        "fail_deferred_execution",
        "fail_deferred_execution_in_uow",
        "resume_deferred_execution",
    }

    assert forbidden_statuses.isdisjoint(vars(ApprovalOutboxStatus))
    assert forbidden_fields.isdisjoint(ApprovalOutbox.model_fields)
    assert [name for name in forbidden_symbols if hasattr(outbox_service_module, name)] == []
    assert [name for name in forbidden_symbols if hasattr(ApprovalOutboxService, name)] == []


def test_exception_retry_never_enters_f045_f046_business_resume() -> None:
    retry_sources = (
        inspect.getsource(ApprovalExceptionService.retry_exception_api),
        inspect.getsource(ApprovalExceptionService.retry_execute_failed_api),
    )
    forbidden_business_resume_fragments = (
        "knowledge_space_file_change_request",
        "resume_deferred_execution",
        "dispatch_resumed_execution",
        "prepare_resume",
        "execution_token",
    )

    for source in retry_sources:
        used = [fragment for fragment in forbidden_business_resume_fragments if fragment in source]
        assert used == [], f"Approval exception retry still resumes F045/F046 business execution: {used}"
