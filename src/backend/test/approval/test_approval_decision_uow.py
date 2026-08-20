from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.approval.domain.models.approval_instance import (
    ApprovalActionLog,
    ApprovalException,
    ApprovalInstance,
    ApprovalInstanceStatus,
    ApprovalOutbox,
    ApprovalTask,
    ApprovalTaskStatus,
)
from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository
from bisheng.approval.domain.services.approval_center_service import ApprovalCenterService
from bisheng.approval.domain.services.approval_uow import build_post_commit_effect
from bisheng.common.errcode.approval import (
    ApprovalRequestAlreadyProcessedError,
    ApprovalRequestNotFoundError,
    ApprovalRequestPermissionDeniedError,
)
from bisheng.core.context.tenant import current_tenant_id


@pytest_asyncio.fixture
async def decision_db(monkeypatch: pytest.MonkeyPatch):
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [
        ApprovalInstance.__table__,
        ApprovalTask.__table__,
        ApprovalOutbox.__table__,
        ApprovalException.__table__,
        ApprovalActionLog.__table__,
    ]
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: SQLModel.metadata.create_all(sync_conn, tables=tables))

    @asynccontextmanager
    async def factory():
        async with AsyncSession(engine) as session:
            yield session

    monkeypatch.setattr(
        "bisheng.approval.domain.repositories.approval_instance_repository.get_async_db_session",
        factory,
    )
    tenant_token = current_tenant_id.set(42)
    try:
        yield
    finally:
        current_tenant_id.reset(tenant_token)
        await engine.dispose()


async def _seed_decision(
    *,
    scenario_code: str = "menu_access_request",
    applicant_user_id: int = 7,
    approver_user_ids: tuple[int, ...] = (9, 10),
) -> tuple[ApprovalInstance, list[ApprovalTask]]:
    instance = await ApprovalInstanceRepository.create_instance(
        ApprovalInstance(
            tenant_id=42,
            scenario_code=scenario_code,
            scenario_name="decision-uow",
            handler_key=scenario_code,
            business_key=f"decision-uow:{scenario_code}:{applicant_user_id}",
            business_resource_type="test",
            business_resource_id="1",
            business_name="atomic decision",
            applicant_user_id=applicant_user_id,
            applicant_user_name="applicant",
            flow_version_id=None,
            status=ApprovalInstanceStatus.PENDING,
            current_node_name="review",
            payload_snapshot={
                "target_user_id": approver_user_ids[0],
            },
            detail_snapshot={},
        )
    )
    tasks = []
    for approver_user_id in approver_user_ids:
        tasks.append(
            await ApprovalInstanceRepository.create_task(
                ApprovalTask(
                    tenant_id=42,
                    instance_id=instance.id,
                    flow_version_id=0,
                    node_code="review",
                    node_name="review",
                    node_order=1,
                    approver_user_id=approver_user_id,
                    approver_source_type="resolved",
                    node_mode="or",
                    status=ApprovalTaskStatus.PENDING,
                )
            )
        )
    return instance, tasks


def _mock_side_effects():
    return (
        patch.object(ApprovalCenterService, "_write_audit_log", new=AsyncMock()),
        patch.object(ApprovalCenterService, "_send_approval_notify", new=AsyncMock()),
    )


def test_center_dispatch_uses_explicit_tenant_when_context_is_wrong():
    tenant_token = current_tenant_id.set(999)
    try:
        with patch("bisheng.worker.approval.tasks.execute_approval_outbox.apply_async") as dispatch:
            ApprovalCenterService._dispatch_outbox(71, 42)
    finally:
        current_tenant_id.reset(tenant_token)

    dispatch.assert_called_once_with(args=[71], headers={"tenant_id": 42})


async def test_task_entry_locks_instance_first_and_rereads_after_reconcile(
    decision_db,
    monkeypatch: pytest.MonkeyPatch,
):
    instance, tasks = await _seed_decision()
    order: list[str] = []
    original_lock_instance = ApprovalInstanceRepository.lock_instance_in_session
    original_lock_tasks = ApprovalInstanceRepository.lock_tasks_in_session

    async def track_instance(session, instance_id, *, tenant_id=None):
        order.append("instance")
        return await original_lock_instance(session, instance_id, tenant_id=tenant_id)

    async def track_tasks(session, instance_id, *, tenant_id=None):
        order.append("tasks")
        return await original_lock_tasks(session, instance_id, tenant_id=tenant_id)

    async def reconcile(*, session, instance, trigger):
        assert trigger == "decision"
        stale = await session.get(ApprovalTask, tasks[0].id)
        stale.status = ApprovalTaskStatus.CANCELLED
        replacement = await session.get(ApprovalTask, tasks[1].id)
        replacement.approver_user_id = 9
        session.add(stale)
        session.add(replacement)
        await session.flush()

    monkeypatch.setattr(ApprovalInstanceRepository, "lock_instance_in_session", track_instance)
    monkeypatch.setattr(ApprovalInstanceRepository, "lock_tasks_in_session", track_tasks)
    monkeypatch.setattr(ApprovalCenterService, "_reconcile_pending_approvers_locked", staticmethod(reconcile))
    service = ApprovalCenterService(instance_repository=ApprovalInstanceRepository)

    with _mock_side_effects()[0], _mock_side_effects()[1]:
        with pytest.raises(ApprovalRequestAlreadyProcessedError):
            await service.decide_task(
                task_id=tasks[0].id,
                action="approve",
                operator_user_id=9,
                operator_user_name="reviewer",
                operator_tenant_id=42,
            )

    assert order[:2] == ["instance", "tasks"]
    refreshed = await ApprovalInstanceRepository.get_instance(instance.id)
    assert refreshed.status == ApprovalInstanceStatus.PENDING


async def test_instance_entry_reconciles_then_selects_current_pending_task(decision_db, monkeypatch):
    instance, tasks = await _seed_decision(approver_user_ids=(10,))

    async def reconcile(*, session, instance, trigger):
        current = await session.get(ApprovalTask, tasks[0].id)
        current.approver_user_id = 9
        session.add(current)
        await session.flush()

    monkeypatch.setattr(ApprovalCenterService, "_reconcile_pending_approvers_locked", staticmethod(reconcile))
    service = ApprovalCenterService(instance_repository=ApprovalInstanceRepository)

    with (
        _mock_side_effects()[0],
        _mock_side_effects()[1],
        patch.object(ApprovalCenterService, "_dispatch_outbox") as dispatch,
    ):
        result = await service.decide_instance_for_current_approver(
            instance_id=instance.id,
            action="approve",
            operator_user_id=9,
            operator_user_name="reviewer",
            operator_tenant_id=42,
        )

    assert result["task_id"] == tasks[0].id
    assert result["instance_status"] == ApprovalInstanceStatus.APPROVED
    dispatch.assert_called_once()
    assert dispatch.call_args.args[1] == 42


async def test_decision_dispatch_precedes_notifications_and_stale_dynamic_task_notice_is_dropped(
    decision_db,
    monkeypatch,
):
    instance, tasks = await _seed_decision(approver_user_ids=(9,))
    events: list[str] = []
    stale_notice = build_post_commit_effect(
        f"notify_dynamic_approval_task:{tasks[0].id}",
        lambda: events.append("stale-task-notice"),
    )

    def fail_notification():
        events.append("notification-failed")
        raise RuntimeError("injected notification failure")

    failing_notice = build_post_commit_effect("notify_dynamic_approver_empty:1", fail_notification)

    async def reconcile(*, session, instance, trigger):
        return (stale_notice, failing_notice)

    monkeypatch.setattr(ApprovalCenterService, "_reconcile_pending_approvers_locked", staticmethod(reconcile))
    monkeypatch.setattr(
        ApprovalCenterService,
        "_dispatch_outbox",
        staticmethod(lambda outbox_id, tenant_id: events.append(f"dispatch:{tenant_id}")),
    )
    service = ApprovalCenterService(instance_repository=ApprovalInstanceRepository)

    with _mock_side_effects()[0], _mock_side_effects()[1]:
        result = await service.decide_task(
            task_id=tasks[0].id,
            action="approve",
            operator_user_id=9,
            operator_user_name="reviewer",
            operator_tenant_id=42,
        )

    assert result is None
    assert events == ["dispatch:42", "notification-failed"]
    assert (await ApprovalInstanceRepository.get_instance(instance.id)).status == ApprovalInstanceStatus.APPROVED


async def test_task_entry_cannot_resolve_cross_tenant_instance_or_reconcile(decision_db, monkeypatch):
    _instance, tasks = await _seed_decision(approver_user_ids=(9,))
    reconcile = AsyncMock(return_value=())
    monkeypatch.setattr(ApprovalCenterService, "_reconcile_pending_approvers_locked", reconcile)
    service = ApprovalCenterService(instance_repository=ApprovalInstanceRepository)

    with pytest.raises(ApprovalRequestNotFoundError):
        await service.decide_task(
            task_id=tasks[0].id,
            action="approve",
            operator_user_id=9,
            operator_user_name="reviewer",
            operator_tenant_id=43,
        )

    reconcile.assert_not_awaited()


async def test_or_decision_commits_task_sibling_instance_log_and_outbox_together(decision_db):
    instance, tasks = await _seed_decision()
    service = ApprovalCenterService(instance_repository=ApprovalInstanceRepository)

    token = current_tenant_id.set(42)
    try:
        with (
            _mock_side_effects()[0],
            _mock_side_effects()[1],
            patch("bisheng.worker.approval.tasks.execute_approval_outbox.apply_async") as dispatch,
        ):
            await service.decide_task(
                task_id=tasks[0].id,
                action="approve",
                operator_user_id=9,
                operator_user_name="reviewer",
                operator_tenant_id=42,
            )
    finally:
        current_tenant_id.reset(token)

    saved_tasks = await ApprovalInstanceRepository.list_tasks(instance.id)
    saved_instance = await ApprovalInstanceRepository.get_instance(instance.id)
    logs = await ApprovalInstanceRepository.list_action_logs(instance.id)
    outboxes = await ApprovalInstanceRepository.list_outbox(instance.id)
    assert [task.status for task in saved_tasks] == [ApprovalTaskStatus.APPROVED, ApprovalTaskStatus.SKIPPED]
    assert saved_instance.status == ApprovalInstanceStatus.APPROVED
    assert len(logs) == 1
    assert len(outboxes) == 1
    dispatch.assert_called_once_with(args=[outboxes[0].id], headers={"tenant_id": 42})


async def test_decision_failure_rolls_back_all_locked_writes(decision_db, monkeypatch):
    instance, tasks = await _seed_decision()
    original_flush = ApprovalInstanceRepository.flush_decision_in_session

    async def fail_after_flush(session):
        await original_flush(session)
        raise RuntimeError("injected failure")

    monkeypatch.setattr(ApprovalInstanceRepository, "flush_decision_in_session", fail_after_flush)
    service = ApprovalCenterService(instance_repository=ApprovalInstanceRepository)

    with _mock_side_effects()[0], _mock_side_effects()[1], pytest.raises(RuntimeError, match="injected"):
        await service.decide_task(
            task_id=tasks[0].id,
            action="reject",
            operator_user_id=9,
            operator_user_name="reviewer",
            operator_tenant_id=42,
        )

    saved_tasks = await ApprovalInstanceRepository.list_tasks(instance.id)
    saved_instance = await ApprovalInstanceRepository.get_instance(instance.id)
    assert all(task.status == ApprovalTaskStatus.PENDING for task in saved_tasks)
    assert saved_instance.status == ApprovalInstanceStatus.PENDING
    assert await ApprovalInstanceRepository.list_action_logs(instance.id) == []


async def test_withdraw_uses_instance_first_terminal_lock(decision_db):
    instance, _tasks = await _seed_decision()
    with (
        patch.object(ApprovalCenterService, "_write_audit_log", new=AsyncMock()),
        patch.object(ApprovalCenterService, "_send_approval_notify", new=AsyncMock()),
        patch.object(ApprovalCenterService, "get_instance_detail", new=AsyncMock(return_value={"status": "withdrawn"})),
    ):
        result = await ApprovalCenterService.withdraw_instance(
            instance_id=instance.id,
            operator_user_id=instance.applicant_user_id,
        )

    assert result == {"status": "withdrawn"}
    assert (await ApprovalInstanceRepository.get_instance(instance.id)).status == ApprovalInstanceStatus.WITHDRAWN
    assert all(
        task.status == ApprovalTaskStatus.CANCELLED for task in await ApprovalInstanceRepository.list_tasks(instance.id)
    )


async def test_cancel_and_withdraw_share_one_terminal_transition(decision_db):
    instance, _tasks = await _seed_decision()

    cancelled = await ApprovalInstanceRepository.cancel_pending_instance(
        instance_id=instance.id,
        operator_user_id=1,
        operator_user_name="admin",
        reason="invalid request",
    )
    withdrawn = await ApprovalInstanceRepository.withdraw_pending_instance(
        instance_id=instance.id,
        applicant_user_id=instance.applicant_user_id,
        operator_user_name="applicant",
        reason="too late",
    )

    assert cancelled is not None and cancelled.status == ApprovalInstanceStatus.CANCELLED
    assert withdrawn is None
    logs = await ApprovalInstanceRepository.list_action_logs(instance.id)
    assert [log.action for log in logs] == ["cancelled"]


async def test_f045_self_confirmation_still_rejects_admin_and_accepts_target(decision_db):
    instance, tasks = await _seed_decision(
        scenario_code="resource_user_invite_confirmation",
        approver_user_ids=(9,),
    )
    service = ApprovalCenterService(instance_repository=ApprovalInstanceRepository)

    with pytest.raises(ApprovalRequestPermissionDeniedError):
        await service.decide_task(
            task_id=tasks[0].id,
            action="approve",
            operator_user_id=1,
            operator_user_name="admin",
            operator_tenant_id=42,
            operator_is_admin=True,
        )

    with _mock_side_effects()[0], _mock_side_effects()[1], patch.object(ApprovalCenterService, "_dispatch_outbox"):
        await service.decide_task(
            task_id=tasks[0].id,
            action="approve",
            operator_user_id=9,
            operator_user_name="target",
            operator_tenant_id=42,
        )

    assert (await ApprovalInstanceRepository.get_instance(instance.id)).status == ApprovalInstanceStatus.APPROVED
