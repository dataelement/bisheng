from __future__ import annotations

import inspect
from contextlib import asynccontextmanager
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.approval.domain.models.approval_decision_outbox import ApprovalDecisionOutbox
from bisheng.approval.domain.models.approval_instance import (
    ApprovalActionLog,
    ApprovalException,
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
from bisheng.approval.domain.services.approval_dynamic_assignee_service import ApprovalDynamicAssigneeService
from bisheng.approval.domain.services.approval_notification_service import ApprovalNotificationService
from bisheng.approval.domain.services.approval_registry import ApprovalRegistry
from bisheng.core.context.tenant import current_tenant_id
from bisheng.user.domain.models.user import UserDao

TENANT_ID = 42
SCENARIO_CODE = "knowledge_space_file_change_request"


@pytest_asyncio.fixture
async def reconciliation_db(monkeypatch: pytest.MonkeyPatch):
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

    @asynccontextmanager
    async def session_factory():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr(
        "bisheng.approval.domain.repositories.approval_instance_repository.get_async_db_session",
        session_factory,
    )
    monkeypatch.setattr(
        "bisheng.approval.domain.repositories.approval_query_repository.get_async_db_session",
        session_factory,
    )
    tenant_token = current_tenant_id.set(TENANT_ID)
    try:
        yield engine
    finally:
        current_tenant_id.reset(tenant_token)
        await engine.dispose()


async def _seed_instance(
    *,
    approver_user_ids: tuple[int, ...] = (10, 11),
    decision_delivery: bool = True,
) -> tuple[ApprovalInstance, list[ApprovalTask]]:
    request_id = "request-1"
    payload = {"space_id": 8}
    handler_key = SCENARIO_CODE
    if decision_delivery:
        handler_key = f"{SCENARIO_CODE}_subscriber"
        payload.update(
            {
                "completion_mode": DECISION_DELIVERY_COMPLETION_MODE,
                "business_request_type": "knowledge_space_file_change_request",
                "business_request_id": request_id,
                "request_fingerprint": "fingerprint:request-1",
            }
        )
    instance = await ApprovalInstanceRepository.create_instance(
        ApprovalInstance(
            tenant_id=TENANT_ID,
            scenario_code=SCENARIO_CODE,
            scenario_name="file change",
            handler_key=handler_key,
            business_key="space:8:file:9:rename",
            business_resource_type="knowledge_space_file_change_request",
            business_resource_id=request_id,
            business_name="report.pdf",
            applicant_user_id=7,
            applicant_user_name="applicant",
            flow_version_id=0,
            status=ApprovalInstanceStatus.PENDING,
            current_node_name="space managers",
            payload_snapshot=payload,
            detail_snapshot={},
        )
    )
    tasks = []
    for user_id in approver_user_ids:
        tasks.append(
            await ApprovalInstanceRepository.create_task(
                ApprovalTask(
                    tenant_id=TENANT_ID,
                    instance_id=instance.id,
                    flow_version_id=0,
                    node_code="space_manager_review",
                    node_name="space managers",
                    node_order=1,
                    approver_user_id=user_id,
                    approver_source_type="business_policy",
                    node_mode="or",
                    status=ApprovalTaskStatus.PENDING,
                )
            )
        )
    return instance, tasks


async def _reconcile(
    *,
    instance_id: int,
    approver_user_ids: list[int],
    reason: str = "permission_changed",
):
    return await ApprovalDynamicAssigneeService.reconcile_assignees(
        tenant_id=TENANT_ID,
        instance_id=instance_id,
        approver_user_ids=approver_user_ids,
        reason=reason,
    )


def test_reconcile_application_api_accepts_only_pre_resolved_ids() -> None:
    parameters = inspect.signature(ApprovalDynamicAssigneeService.reconcile_assignees).parameters

    assert tuple(parameters) == ("tenant_id", "instance_id", "approver_user_ids", "reason")
    assert "resolver" not in parameters


async def test_reconcile_locks_instance_first_then_cancels_and_adds_tasks(
    reconciliation_db,
) -> None:
    instance, original_tasks = await _seed_instance()
    lock_order: list[str] = []
    original_instance_lock = ApprovalInstanceRepository.lock_instance_in_session
    original_task_lock = ApprovalInstanceRepository.lock_tasks_in_session
    original_terminal_lock = ApprovalInstanceRepository.lock_open_exceptions_and_outboxes_in_session

    async def lock_instance(*args, **kwargs):
        lock_order.append("instance")
        return await original_instance_lock(*args, **kwargs)

    async def lock_tasks(*args, **kwargs):
        lock_order.append("tasks")
        return await original_task_lock(*args, **kwargs)

    async def lock_terminal_rows(*args, **kwargs):
        lock_order.append("exceptions/outboxes")
        return await original_terminal_lock(*args, **kwargs)

    with (
        patch.object(ApprovalInstanceRepository, "lock_instance_in_session", side_effect=lock_instance),
        patch.object(ApprovalInstanceRepository, "lock_tasks_in_session", side_effect=lock_tasks),
        patch.object(
            ApprovalInstanceRepository,
            "lock_open_exceptions_and_outboxes_in_session",
            side_effect=lock_terminal_rows,
        ),
        patch.object(ApprovalNotificationService, "notify_user", new=AsyncMock()),
    ):
        result = await _reconcile(instance_id=instance.id, approver_user_ids=[11, 12, 12])

    tasks = await ApprovalInstanceRepository.list_tasks(instance.id)
    assert lock_order[:3] == ["instance", "tasks", "exceptions/outboxes"]
    assert [(task.approver_user_id, task.status) for task in tasks] == [
        (10, ApprovalTaskStatus.CANCELLED),
        (11, ApprovalTaskStatus.PENDING),
        (12, ApprovalTaskStatus.PENDING),
    ]
    assert result.removed_user_ids == (10,)
    assert result.added_user_ids == (12,)
    assert original_tasks[0].id in result.cancelled_task_ids


async def test_reconcile_maintains_one_approver_empty_exception_and_recovers(
    reconciliation_db,
) -> None:
    instance, _tasks = await _seed_instance(approver_user_ids=(10,))

    with (
        patch.object(ApprovalNotificationService, "notify_user", new=AsyncMock()),
        patch.object(ApprovalNotificationService, "notify_admins", new=AsyncMock()) as notify_admins,
    ):
        first = await _reconcile(instance_id=instance.id, approver_user_ids=[], reason="permission_changed")
        repeated = await _reconcile(instance_id=instance.id, approver_user_ids=[], reason="beat")
        recovered = await _reconcile(instance_id=instance.id, approver_user_ids=[12], reason="lazy_page")

    saved = await ApprovalInstanceRepository.get_instance(instance.id)
    exceptions = await ApprovalInstanceRepository.list_exceptions(instance.id)
    assert first.entered_approver_empty is True
    assert repeated.entered_approver_empty is False
    assert recovered.resolved_approver_empty is True
    assert saved.status == ApprovalInstanceStatus.PENDING
    assert len(exceptions) == 1
    assert exceptions[0].status == "resolved"
    assert exceptions[0].resolved_action == "approvers_reconciled"
    notify_admins.assert_awaited_once()


@pytest.mark.parametrize(
    "terminal_status",
    [
        ApprovalTaskStatus.APPROVED,
        ApprovalTaskStatus.REJECTED,
        ApprovalTaskStatus.CANCELLED,
        ApprovalTaskStatus.SKIPPED,
    ],
)
async def test_reconcile_never_revives_terminal_task_eligibility(
    reconciliation_db,
    terminal_status: str,
) -> None:
    instance, tasks = await _seed_instance(approver_user_ids=(10, 11))
    historical_task = tasks[0]
    historical_task.status = terminal_status
    await ApprovalInstanceRepository.update_task(historical_task)

    with patch.object(ApprovalNotificationService, "notify_user", new=AsyncMock()):
        await _reconcile(instance_id=instance.id, approver_user_ids=[10, 11])

    user_tasks = [
        task for task in await ApprovalInstanceRepository.list_tasks(instance.id) if task.approver_user_id == 10
    ]
    assert len(user_tasks) == 2
    assert user_tasks[0].id == historical_task.id
    assert user_tasks[0].status == terminal_status
    assert user_tasks[1].id != historical_task.id
    assert user_tasks[1].status == ApprovalTaskStatus.PENDING


def test_approval_list_and_detail_sources_do_not_call_business_discovery_or_visibility_hooks() -> None:
    query_methods = (
        ApprovalCenterService.list_my_tasks,
        ApprovalCenterService.list_my_requests,
        ApprovalCenterService.get_task_detail,
        ApprovalCenterService.get_instance_detail,
    )
    forbidden_calls = {
        "_prepare_dynamic_tasks",
        "_filter_visible_instances",
        "_authorize_view",
        "_get_business_status_projection",
    }

    for method in query_methods:
        source = inspect.getsource(method)
        used_calls = {name for name in forbidden_calls if name in source}
        assert used_calls == set(), f"{method.__name__} still calls business hooks: {sorted(used_calls)}"


@pytest.mark.parametrize("query_name", ["list_my_tasks", "get_instance_detail"])
async def test_decision_delivery_queries_never_construct_a_knowledge_runtime_handler(
    reconciliation_db,
    query_name: str,
) -> None:
    instance, _tasks = await _seed_instance(approver_user_ids=(10,))
    login_user = SimpleNamespace(user_id=10, tenant_id=TENANT_ID, is_admin=lambda: False)

    with (
        patch(
            "bisheng.approval.domain.services.approval_center_service.build_runtime_handler",
            new=AsyncMock(side_effect=AssertionError("approval query crossed into Knowledge")),
        ) as build_handler,
        patch.object(UserDao, "aget_user_by_ids", new=AsyncMock(return_value=[])),
    ):
        if query_name == "list_my_tasks":
            result = await ApprovalCenterService.list_my_tasks(
                tenant_id=TENANT_ID,
                approver_user_id=10,
            )
        else:
            result = await ApprovalCenterService.get_instance_detail(
                instance_id=instance.id,
                login_user=login_user,
            )

    if query_name == "list_my_tasks":
        assert result["total"] == 1
    else:
        assert result["instance_id"] == instance.id
    build_handler.assert_not_awaited()


@dataclass
class FailingPolicy:
    scenario_code: str = SCENARIO_CODE
    protocol_version: int = APPROVAL_SCENARIO_POLICY_PROTOCOL_VERSION
    completion_mode: str = DECISION_DELIVERY_COMPLETION_MODE

    async def validate_submission(self, command: ApprovalSubmissionCommand) -> None:
        del command

    async def authorize_decision(self, context: ApprovalDecisionContext) -> None:
        del context
        raise RuntimeError("strict owner lookup unavailable")


@dataclass
class StubSubscriber:
    scenario_code: str = SCENARIO_CODE
    subscriber_key: str = f"{SCENARIO_CODE}_subscriber"
    protocol_version: int = APPROVAL_DECISION_SUBSCRIBER_PROTOCOL_VERSION
    event_version: int = APPROVAL_DECISION_EVENT_VERSION
    completion_mode: str = DECISION_DELIVERY_COMPLETION_MODE

    async def accept(self, event: ApprovalDecisionEvent) -> None:
        del event


async def test_policy_failure_closes_only_the_decision_and_rolls_back_terminal_writes(
    reconciliation_db,
) -> None:
    instance, tasks = await _seed_instance(approver_user_ids=(10,))
    registry = ApprovalRegistry()
    registry.register_policy(FailingPolicy())
    registry.register_subscriber(StubSubscriber())
    registry.freeze_decision_delivery(required_scenario_codes={SCENARIO_CODE})
    service = ApprovalCenterService(
        instance_repository=ApprovalInstanceRepository,
        registry=registry,
    )

    with pytest.raises(RuntimeError, match="strict owner lookup unavailable"):
        await service.decide_task(
            task_id=tasks[0].id,
            action="approve",
            operator_user_id=10,
            operator_user_name="reviewer",
            operator_tenant_id=TENANT_ID,
        )

    saved_instance = await ApprovalInstanceRepository.get_instance(instance.id)
    saved_task = await ApprovalInstanceRepository.get_task(tasks[0].id)
    action_logs = await ApprovalInstanceRepository.list_action_logs(instance.id)
    async with AsyncSession(reconciliation_db) as session:
        decision_events = list((await session.exec(select(ApprovalDecisionOutbox))).all())
    assert saved_instance.status == ApprovalInstanceStatus.PENDING
    assert saved_task.status == ApprovalTaskStatus.PENDING
    assert action_logs == []
    assert decision_events == []
