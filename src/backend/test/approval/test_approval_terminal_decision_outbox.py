from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.approval.domain.models.approval_decision_outbox import (
    ApprovalDecisionOutbox,
    ApprovalDecisionOutboxStatus,
)
from bisheng.approval.domain.models.approval_instance import (
    ApprovalActionLog,
    ApprovalException,
    ApprovalExceptionType,
    ApprovalInstance,
    ApprovalInstanceStatus,
    ApprovalOutbox,
    ApprovalTask,
    ApprovalTaskStatus,
)
from bisheng.approval.domain.ports.decision_subscriber import (
    APPROVAL_DECISION_EVENT_VERSION,
    APPROVAL_DECISION_SUBSCRIBER_PROTOCOL_VERSION,
    ApprovalDecisionEvent,
)
from bisheng.approval.domain.ports.scenario_policy import (
    APPROVAL_SCENARIO_POLICY_PROTOCOL_VERSION,
    DECISION_DELIVERY_COMPLETION_MODE,
    ApprovalDecisionContext,
    ApprovalSubmissionCommand,
)
from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository
from bisheng.approval.domain.services.approval_center_service import ApprovalCenterService
from bisheng.approval.domain.services.approval_exception_service import ApprovalExceptionService
from bisheng.approval.domain.services.approval_registry import ApprovalRegistry
from bisheng.common.errcode.approval import (
    ApprovalRequestAlreadyProcessedError,
    ApprovalRequestPermissionDeniedError,
)
from bisheng.core.context.tenant import current_tenant_id

TENANT_ID = 42
F045_SCENARIO = "resource_user_invite_confirmation"
F046_SCENARIO = "knowledge_space_file_change_request"


@dataclass
class StubPolicy:
    scenario_code: str
    allowed_operator_user_id: int | None = None
    authorization_error: Exception | None = None
    protocol_version: int = APPROVAL_SCENARIO_POLICY_PROTOCOL_VERSION
    completion_mode: str = DECISION_DELIVERY_COMPLETION_MODE
    decision_contexts: list[ApprovalDecisionContext] = field(default_factory=list)

    async def validate_submission(self, command: ApprovalSubmissionCommand) -> None:
        del command

    async def authorize_decision(self, context: ApprovalDecisionContext) -> None:
        self.decision_contexts.append(context)
        if self.authorization_error is not None:
            raise self.authorization_error
        if self.allowed_operator_user_id is not None and context.operator_user_id != self.allowed_operator_user_id:
            raise ApprovalRequestPermissionDeniedError()


@dataclass
class StubSubscriber:
    scenario_code: str
    subscriber_key: str
    protocol_version: int = APPROVAL_DECISION_SUBSCRIBER_PROTOCOL_VERSION
    event_version: int = APPROVAL_DECISION_EVENT_VERSION
    completion_mode: str = DECISION_DELIVERY_COMPLETION_MODE

    async def accept(self, event: ApprovalDecisionEvent) -> None:
        del event


@pytest_asyncio.fixture
async def terminal_decision_db(monkeypatch: pytest.MonkeyPatch):
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [
        ApprovalInstance.__table__,
        ApprovalTask.__table__,
        ApprovalOutbox.__table__,
        ApprovalDecisionOutbox.__table__,
        ApprovalException.__table__,
        ApprovalActionLog.__table__,
    ]
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync_connection: SQLModel.metadata.create_all(sync_connection, tables=tables))

    # SQLite does not implement row-level FOR UPDATE. Serialize UoWs while
    # still launching concurrent callers so the test models production lock semantics.
    uow_lock = asyncio.Lock()

    @asynccontextmanager
    async def session_factory():
        async with uow_lock:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                yield session

    monkeypatch.setattr(
        "bisheng.approval.domain.repositories.approval_instance_repository.get_async_db_session",
        session_factory,
    )
    tenant_token = current_tenant_id.set(TENANT_ID)
    try:
        yield engine
    finally:
        current_tenant_id.reset(tenant_token)
        await engine.dispose()


def _registry(policy: StubPolicy) -> ApprovalRegistry:
    registry = ApprovalRegistry()
    registry.register_policy(policy)
    registry.register_subscriber(
        StubSubscriber(
            scenario_code=policy.scenario_code,
            subscriber_key=f"{policy.scenario_code}_subscriber",
        )
    )
    registry.freeze_decision_delivery(required_scenario_codes={policy.scenario_code})
    return registry


async def _seed_terminal_instance(
    *,
    scenario_code: str = F046_SCENARIO,
    request_suffix: str = "1",
    applicant_user_id: int = 7,
    approver_user_id: int = 9,
    status: str = ApprovalInstanceStatus.PENDING,
    target_in_detail_snapshot: bool = False,
) -> tuple[ApprovalInstance, ApprovalTask]:
    # Real F045 submissions keep the invitee in `detail_snapshot` and reserve
    # `payload_snapshot` for the decision-delivery envelope; older instances carry it in
    # the payload. Seed either shape so both stay covered.
    payload_snapshot = {
        "completion_mode": DECISION_DELIVERY_COMPLETION_MODE,
        "business_request_type": "test_business_request",
        "business_request_id": request_suffix,
        "request_fingerprint": f"fingerprint:{request_suffix}",
    }
    detail_snapshot: dict = {}
    if target_in_detail_snapshot:
        detail_snapshot["target_user_id"] = approver_user_id
    else:
        payload_snapshot["target_user_id"] = approver_user_id
    instance = await ApprovalInstanceRepository.create_instance(
        ApprovalInstance(
            tenant_id=TENANT_ID,
            scenario_code=scenario_code,
            scenario_name="decision delivery",
            handler_key=f"{scenario_code}_subscriber",
            business_key=f"business:{scenario_code}:{request_suffix}",
            business_resource_type="test_business_request",
            business_resource_id=request_suffix,
            business_name="terminal decision",
            applicant_user_id=applicant_user_id,
            applicant_user_name="applicant",
            status=status,
            current_node_name="review",
            payload_snapshot=payload_snapshot,
            detail_snapshot=detail_snapshot,
        )
    )
    task = await ApprovalInstanceRepository.create_task(
        ApprovalTask(
            tenant_id=TENANT_ID,
            instance_id=instance.id,
            flow_version_id=0,
            node_code="review",
            node_name="review",
            node_order=1,
            approver_user_id=approver_user_id,
            approver_source_type="business_policy",
            node_mode="or",
            status=ApprovalTaskStatus.PENDING,
        )
    )
    return instance, task


async def _events(engine, *, instance_id: int | None = None) -> list[ApprovalDecisionOutbox]:
    async with AsyncSession(engine) as session:
        statement = select(ApprovalDecisionOutbox).order_by(ApprovalDecisionOutbox.id.asc())
        if instance_id is not None:
            statement = statement.where(ApprovalDecisionOutbox.instance_id == instance_id)
        return list((await session.exec(statement)).all())


async def _legacy_outboxes(engine, instance_id: int) -> list[ApprovalOutbox]:
    async with AsyncSession(engine) as session:
        return list((await session.exec(select(ApprovalOutbox).where(ApprovalOutbox.instance_id == instance_id))).all())


def _center(policy: StubPolicy) -> ApprovalCenterService:
    return ApprovalCenterService(
        instance_repository=ApprovalInstanceRepository,
        registry=_registry(policy),
    )


def _mock_center_side_effects():
    return (
        patch.object(ApprovalCenterService, "_write_audit_log", new=AsyncMock()),
        patch.object(ApprovalCenterService, "_send_approval_notify", new=AsyncMock()),
        patch.object(ApprovalCenterService, "_send_invite_notify_best_effort", new=AsyncMock()),
        patch.object(ApprovalCenterService, "_run_terminal_hook_best_effort", new=AsyncMock()),
    )


def _assert_event(
    event: ApprovalDecisionOutbox,
    *,
    instance: ApprovalInstance,
    decision: str,
    operator_user_id: int,
) -> None:
    assert event.tenant_id == TENANT_ID
    assert event.instance_id == instance.id
    assert event.scenario_code == instance.scenario_code
    assert event.subscriber_key == f"{instance.scenario_code}_subscriber"
    assert event.business_request_type == "test_business_request"
    assert event.business_request_id == instance.business_resource_id
    assert event.business_key == instance.business_key
    assert event.request_fingerprint == f"fingerprint:{instance.business_resource_id}"
    assert event.decision == decision
    assert event.decision_version == 1
    assert event.event_version == APPROVAL_DECISION_EVENT_VERSION
    assert event.operator_user_id == operator_user_id
    assert event.decided_at is not None
    assert event.status == ApprovalDecisionOutboxStatus.PENDING


def _fail_decision_event_add(monkeypatch: pytest.MonkeyPatch) -> None:
    original_add = AsyncSession.add

    def fail_on_decision_event(self, row, *args, **kwargs):
        if isinstance(row, ApprovalDecisionOutbox):
            raise RuntimeError("injected decision event failure")
        return original_add(self, row, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "add", fail_on_decision_event)


@pytest.mark.parametrize(
    ("action", "expected_status", "expected_decision"),
    [
        ("approve", ApprovalInstanceStatus.APPROVED, "approved"),
        ("reject", ApprovalInstanceStatus.REJECTED, "rejected"),
    ],
)
async def test_last_node_decision_commits_terminal_state_and_one_decision_event(
    terminal_decision_db,
    action: str,
    expected_status: str,
    expected_decision: str,
) -> None:
    instance, task = await _seed_terminal_instance()
    service = _center(StubPolicy(scenario_code=F046_SCENARIO))

    with (
        _mock_center_side_effects()[0],
        _mock_center_side_effects()[1],
        _mock_center_side_effects()[2],
        _mock_center_side_effects()[3],
        patch.object(ApprovalCenterService, "_dispatch_outbox") as legacy_dispatch,
    ):
        await service.decide_task(
            task_id=task.id,
            action=action,
            operator_user_id=task.approver_user_id,
            operator_user_name="reviewer",
            operator_tenant_id=TENANT_ID,
        )

    saved = await ApprovalInstanceRepository.get_instance(instance.id)
    events = await _events(terminal_decision_db, instance_id=instance.id)
    assert saved.status == expected_status
    assert len(events) == 1
    _assert_event(
        events[0],
        instance=instance,
        decision=expected_decision,
        operator_user_id=task.approver_user_id,
    )
    assert await _legacy_outboxes(terminal_decision_db, instance.id) == []
    legacy_dispatch.assert_not_called()


async def test_withdraw_commits_terminal_state_and_decision_event(terminal_decision_db) -> None:
    instance, _task = await _seed_terminal_instance(applicant_user_id=7)

    with (
        patch.object(ApprovalCenterService, "_write_audit_log", new=AsyncMock()),
        patch.object(ApprovalCenterService, "_send_approval_notify", new=AsyncMock()),
        patch.object(ApprovalCenterService, "_run_terminal_hook_best_effort", new=AsyncMock()),
        patch.object(
            ApprovalCenterService,
            "get_instance_detail",
            new=AsyncMock(return_value={"status": ApprovalInstanceStatus.WITHDRAWN}),
        ),
    ):
        result = await ApprovalCenterService.withdraw_instance(
            instance_id=instance.id,
            operator_user_id=instance.applicant_user_id,
            operator_user_name="applicant",
            reason="no longer needed",
        )

    saved = await ApprovalInstanceRepository.get_instance(instance.id)
    events = await _events(terminal_decision_db, instance_id=instance.id)
    assert result == {"status": ApprovalInstanceStatus.WITHDRAWN}
    assert saved.status == ApprovalInstanceStatus.WITHDRAWN
    assert len(events) == 1
    _assert_event(
        events[0],
        instance=instance,
        decision="withdrawn",
        operator_user_id=instance.applicant_user_id,
    )


async def test_exception_cancel_commits_terminal_state_and_decision_event(terminal_decision_db) -> None:
    instance, _task = await _seed_terminal_instance(status=ApprovalInstanceStatus.EXCEPTION)
    exception = await ApprovalInstanceRepository.create_exception(
        ApprovalException(
            tenant_id=TENANT_ID,
            instance_id=instance.id,
            exception_type=ApprovalExceptionType.APPROVER_EMPTY,
            detail={"node_code": "review", "node_order": 1},
        )
    )
    exception_policy = AsyncMock(return_value=True)
    runtime_handler = SimpleNamespace(exception_action_policy=exception_policy)

    with (
        patch.object(ApprovalExceptionService, "_build_handler", new=AsyncMock(return_value=runtime_handler)),
        patch.object(ApprovalExceptionService, "_write_audit_log", new=AsyncMock()),
        patch.object(ApprovalExceptionService, "_notify_user", new=AsyncMock()),
    ):
        result = await ApprovalExceptionService.cancel_exception_api(
            exception_id=exception.id,
            operator_user_id=1,
            reason="invalid request",
        )

    saved = await ApprovalInstanceRepository.get_instance(instance.id)
    events = await _events(terminal_decision_db, instance_id=instance.id)
    assert result["status"] == "cancelled"
    assert saved.status == ApprovalInstanceStatus.CANCELLED
    assert len(events) == 1
    _assert_event(events[0], instance=instance, decision="cancelled", operator_user_id=1)


async def test_terminal_failure_rolls_back_task_instance_log_and_decision_event(
    terminal_decision_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, task = await _seed_terminal_instance()
    _fail_decision_event_add(monkeypatch)
    service = _center(StubPolicy(scenario_code=F046_SCENARIO))

    with (
        _mock_center_side_effects()[0],
        _mock_center_side_effects()[1],
        _mock_center_side_effects()[2],
        _mock_center_side_effects()[3],
        pytest.raises(RuntimeError, match="injected decision event failure"),
    ):
        await service.decide_task(
            task_id=task.id,
            action="reject",
            operator_user_id=task.approver_user_id,
            operator_user_name="reviewer",
            operator_tenant_id=TENANT_ID,
        )

    saved = await ApprovalInstanceRepository.get_instance(instance.id)
    saved_task = await ApprovalInstanceRepository.get_task(task.id)
    assert saved.status == ApprovalInstanceStatus.PENDING
    assert saved_task.status == ApprovalTaskStatus.PENDING
    assert await ApprovalInstanceRepository.list_action_logs(instance.id) == []
    assert await _events(terminal_decision_db, instance_id=instance.id) == []


async def test_withdraw_rolls_back_when_decision_event_cannot_be_written(
    terminal_decision_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, task = await _seed_terminal_instance(applicant_user_id=7)
    _fail_decision_event_add(monkeypatch)

    with (
        patch.object(ApprovalCenterService, "_write_audit_log", new=AsyncMock()),
        patch.object(ApprovalCenterService, "_send_approval_notify", new=AsyncMock()),
        patch.object(ApprovalCenterService, "_run_terminal_hook_best_effort", new=AsyncMock()),
        patch.object(
            ApprovalCenterService,
            "get_instance_detail",
            new=AsyncMock(return_value={"status": ApprovalInstanceStatus.WITHDRAWN}),
        ),
        pytest.raises(RuntimeError, match="injected decision event failure"),
    ):
        await ApprovalCenterService.withdraw_instance(
            instance_id=instance.id,
            operator_user_id=instance.applicant_user_id,
            operator_user_name="applicant",
            reason="no longer needed",
        )

    assert (await ApprovalInstanceRepository.get_instance(instance.id)).status == ApprovalInstanceStatus.PENDING
    assert (await ApprovalInstanceRepository.get_task(task.id)).status == ApprovalTaskStatus.PENDING
    assert await ApprovalInstanceRepository.list_action_logs(instance.id) == []
    assert await _events(terminal_decision_db, instance_id=instance.id) == []


async def test_exception_cancel_rolls_back_when_decision_event_cannot_be_written(
    terminal_decision_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, task = await _seed_terminal_instance(status=ApprovalInstanceStatus.EXCEPTION)
    exception = await ApprovalInstanceRepository.create_exception(
        ApprovalException(
            tenant_id=TENANT_ID,
            instance_id=instance.id,
            exception_type=ApprovalExceptionType.APPROVER_EMPTY,
            detail={"node_code": "review", "node_order": 1},
        )
    )
    _fail_decision_event_add(monkeypatch)
    runtime_handler = SimpleNamespace(exception_action_policy=AsyncMock(return_value=True))

    with (
        patch.object(ApprovalExceptionService, "_build_handler", new=AsyncMock(return_value=runtime_handler)),
        patch.object(ApprovalExceptionService, "_write_audit_log", new=AsyncMock()),
        patch.object(ApprovalExceptionService, "_notify_user", new=AsyncMock()),
        pytest.raises(RuntimeError, match="injected decision event failure"),
    ):
        await ApprovalExceptionService.cancel_exception_api(
            exception_id=exception.id,
            operator_user_id=1,
            reason="invalid request",
        )

    assert (await ApprovalInstanceRepository.get_instance(instance.id)).status == ApprovalInstanceStatus.EXCEPTION
    assert (await ApprovalInstanceRepository.get_task(task.id)).status == ApprovalTaskStatus.PENDING
    saved_exception = await ApprovalInstanceRepository.get_exception(exception.id)
    assert saved_exception.status == "open"
    assert await ApprovalInstanceRepository.list_action_logs(instance.id) == []
    assert await _events(terminal_decision_db, instance_id=instance.id) == []


async def test_instance_batch_style_decisions_create_one_event_per_item(terminal_decision_db) -> None:
    first, _ = await _seed_terminal_instance(request_suffix="batch-1")
    second, _ = await _seed_terminal_instance(request_suffix="batch-2")
    service = _center(StubPolicy(scenario_code=F046_SCENARIO))

    with (
        _mock_center_side_effects()[0],
        _mock_center_side_effects()[1],
        _mock_center_side_effects()[2],
        _mock_center_side_effects()[3],
        patch.object(ApprovalCenterService, "_dispatch_outbox"),
    ):
        results = await asyncio.gather(
            *(
                service.decide_instance_for_current_approver(
                    instance_id=instance.id,
                    action="approve",
                    operator_user_id=9,
                    operator_user_name="reviewer",
                    operator_tenant_id=TENANT_ID,
                )
                for instance in (first, second)
            )
        )

    assert {result["instance_id"] for result in results} == {first.id, second.id}
    events = await _events(terminal_decision_db)
    assert {(event.instance_id, event.decision_version) for event in events} == {
        (first.id, 1),
        (second.id, 1),
    }


async def test_concurrent_double_decision_creates_only_one_terminal_event(terminal_decision_db) -> None:
    instance, _task = await _seed_terminal_instance(request_suffix="concurrent")
    service = _center(StubPolicy(scenario_code=F046_SCENARIO))

    with (
        _mock_center_side_effects()[0],
        _mock_center_side_effects()[1],
        _mock_center_side_effects()[2],
        _mock_center_side_effects()[3],
        patch.object(ApprovalCenterService, "_dispatch_outbox"),
    ):
        results = await asyncio.gather(
            *(
                service.decide_instance_for_current_approver(
                    instance_id=instance.id,
                    action="approve",
                    operator_user_id=9,
                    operator_user_name="reviewer",
                    operator_tenant_id=TENANT_ID,
                )
                for _ in range(2)
            ),
            return_exceptions=True,
        )

    assert sum(not isinstance(result, Exception) for result in results) == 1
    errors = [result for result in results if isinstance(result, Exception)]
    assert len(errors) == 1
    assert isinstance(errors[0], (ApprovalRequestAlreadyProcessedError, ApprovalRequestPermissionDeniedError))
    events = await _events(terminal_decision_db, instance_id=instance.id)
    assert len(events) == 1
    assert events[0].decision_version == 1


async def test_f045_policy_runs_before_admin_override_and_denies_admin(terminal_decision_db) -> None:
    instance, task = await _seed_terminal_instance(
        scenario_code=F045_SCENARIO,
        approver_user_id=9,
    )
    policy = StubPolicy(scenario_code=F045_SCENARIO, allowed_operator_user_id=9)
    service = _center(policy)

    with pytest.raises(ApprovalRequestPermissionDeniedError):
        await service.decide_task(
            task_id=task.id,
            action="approve",
            operator_user_id=1,
            operator_user_name="admin",
            operator_tenant_id=TENANT_ID,
            operator_is_admin=True,
        )

    assert len(policy.decision_contexts) == 1
    assert policy.decision_contexts[0].operator_user_id == 1
    assert (await ApprovalInstanceRepository.get_instance(instance.id)).status == ApprovalInstanceStatus.PENDING
    assert await _events(terminal_decision_db, instance_id=instance.id) == []


async def test_f046_policy_failure_is_fail_closed_and_writes_no_terminal_event(terminal_decision_db) -> None:
    instance, task = await _seed_terminal_instance()
    policy = StubPolicy(
        scenario_code=F046_SCENARIO,
        authorization_error=RuntimeError("strict owner lookup unavailable"),
    )
    service = _center(policy)

    with pytest.raises(RuntimeError, match="strict owner lookup unavailable"):
        await service.decide_task(
            task_id=task.id,
            action="approve",
            operator_user_id=task.approver_user_id,
            operator_user_name="reviewer",
            operator_tenant_id=TENANT_ID,
        )

    assert len(policy.decision_contexts) == 1
    assert (await ApprovalInstanceRepository.get_instance(instance.id)).status == ApprovalInstanceStatus.PENDING
    assert (await ApprovalInstanceRepository.get_task(task.id)).status == ApprovalTaskStatus.PENDING
    assert await _events(terminal_decision_db, instance_id=instance.id) == []


async def test_f045_invitee_approves_with_target_user_in_detail_snapshot(terminal_decision_db) -> None:
    """The invitee's own confirmation must pass the self-confirmation guard.

    Production F045 instances keep `target_user_id` in `detail_snapshot`, so reading it
    from `payload_snapshot` denied every invitee their own invite.
    """

    instance, task = await _seed_terminal_instance(
        scenario_code=F045_SCENARIO,
        approver_user_id=9,
        target_in_detail_snapshot=True,
    )
    policy = StubPolicy(scenario_code=F045_SCENARIO, allowed_operator_user_id=9)
    service = _center(policy)

    with (
        _mock_center_side_effects()[0],
        _mock_center_side_effects()[1],
        _mock_center_side_effects()[2],
        _mock_center_side_effects()[3],
    ):
        await service.decide_task(
            task_id=task.id,
            action="approve",
            operator_user_id=9,
            operator_user_name="invitee",
            operator_tenant_id=TENANT_ID,
        )

    saved = await ApprovalInstanceRepository.get_instance(instance.id)
    events = await _events(terminal_decision_db, instance_id=instance.id)
    assert saved.status == ApprovalInstanceStatus.APPROVED
    assert len(events) == 1
    _assert_event(events[0], instance=instance, decision="approved", operator_user_id=9)


async def test_terminal_decision_dispatches_the_delivery_worker(terminal_decision_db) -> None:
    """A committed decision event must wake the delivery worker.

    Nothing else polls `approval_decision_outbox`, so a missing dispatch leaves the event
    pending forever and the approved business request never advances.
    """

    instance, task = await _seed_terminal_instance()
    service = _center(StubPolicy(scenario_code=F046_SCENARIO))

    with (
        _mock_center_side_effects()[0],
        _mock_center_side_effects()[1],
        _mock_center_side_effects()[2],
        _mock_center_side_effects()[3],
        patch.object(ApprovalCenterService, "_dispatch_decision_delivery") as dispatch,
    ):
        await service.decide_task(
            task_id=task.id,
            action="approve",
            operator_user_id=task.approver_user_id,
            operator_user_name="reviewer",
            operator_tenant_id=TENANT_ID,
        )

    assert len(await _events(terminal_decision_db, instance_id=instance.id)) == 1
    dispatch.assert_called_once_with(TENANT_ID)
