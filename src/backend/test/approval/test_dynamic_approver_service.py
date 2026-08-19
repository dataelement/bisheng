from __future__ import annotations

import asyncio
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
from bisheng.approval.domain.services.approval_dynamic_assignee_service import ApprovalDynamicAssigneeService
from bisheng.approval.domain.services.approval_notification_service import ApprovalNotificationService
from bisheng.core.context.tenant import current_tenant_id


@pytest_asyncio.fixture
async def dynamic_db(monkeypatch: pytest.MonkeyPatch):
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
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr(
        "bisheng.approval.domain.repositories.approval_instance_repository.get_async_db_session",
        factory,
    )
    tenant_token = current_tenant_id.set(42)
    try:
        yield factory
    finally:
        current_tenant_id.reset(tenant_token)
        await engine.dispose()


async def _seed_dynamic(*, approvers: tuple[int, ...] = (10, 11)) -> tuple[ApprovalInstance, list[ApprovalTask]]:
    instance = await ApprovalInstanceRepository.create_instance(
        ApprovalInstance(
            tenant_id=42,
            scenario_code="knowledge_space_file_change_request",
            scenario_name="file change",
            handler_key="knowledge_space_file_change_request",
            business_key="space:8:file:9:rename",
            business_resource_type="knowledge_file",
            business_resource_id="9",
            business_name="report.pdf",
            applicant_user_id=7,
            applicant_user_name="applicant",
            flow_version_id=5,
            status=ApprovalInstanceStatus.PENDING,
            current_node_name="space managers",
            payload_snapshot={"space_id": 8},
            detail_snapshot={},
        )
    )
    tasks = []
    for user_id in approvers:
        tasks.append(
            await ApprovalInstanceRepository.create_task(
                ApprovalTask(
                    tenant_id=42,
                    instance_id=instance.id,
                    flow_version_id=5,
                    node_code="space_manager_review",
                    node_name="space managers",
                    node_order=1,
                    approver_user_id=user_id,
                    approver_source_type="resolved",
                    node_mode="or",
                    status=ApprovalTaskStatus.PENDING,
                )
            )
        )
    return instance, tasks


async def _all_rows(instance_id: int):
    return (
        await ApprovalInstanceRepository.get_instance(instance_id),
        await ApprovalInstanceRepository.list_tasks(instance_id),
        await ApprovalInstanceRepository.list_exceptions(instance_id),
        await ApprovalInstanceRepository.list_action_logs(instance_id),
    )


async def test_reconcile_cancels_removed_adds_new_and_notifies_only_after_commit(dynamic_db):
    instance, tasks = await _seed_dynamic()
    observed_committed_status: list[str] = []

    async def notify_user(**kwargs):
        saved = await ApprovalInstanceRepository.list_tasks(instance.id)
        created = next(row for row in saved if row.id == kwargs["task_id"])
        observed_committed_status.append(created.status)

    with patch.object(ApprovalNotificationService, "notify_user", side_effect=notify_user) as notify:
        result = await ApprovalDynamicAssigneeService.reconcile_instance(
            instance_id=instance.id,
            resolver=AsyncMock(return_value=[11, 12, 12]),
            trigger="permission_changed",
            operator_user_id=99,
        )

    saved_instance, saved_tasks, exceptions, logs = await _all_rows(instance.id)
    assert saved_instance.status == ApprovalInstanceStatus.PENDING
    assert exceptions == []
    assert [(row.approver_user_id, row.status) for row in saved_tasks] == [
        (10, ApprovalTaskStatus.CANCELLED),
        (11, ApprovalTaskStatus.PENDING),
        (12, ApprovalTaskStatus.PENDING),
    ]
    assert result.added_user_ids == (12,)
    assert result.removed_user_ids == (10,)
    assert len(logs) == 1
    assert logs[0].action == "approval.approvers.reconciled"
    assert logs[0].operator_user_id == 99
    assert logs[0].detail == {
        "added_user_ids": [12],
        "removed_user_ids": [10],
        "trigger": "permission_changed",
        "operator_user_id": 99,
    }
    notify.assert_awaited_once()
    assert observed_committed_status == [ApprovalTaskStatus.PENDING]
    assert tasks[0].id in result.cancelled_task_ids


async def test_dynamic_notifications_are_independently_best_effort(dynamic_db):
    instance, _ = await _seed_dynamic(approvers=(10,))
    notified_user_ids: list[int] = []

    async def notify_user(**kwargs):
        notified_user_ids.append(kwargs["receiver_user_id"])
        if kwargs["receiver_user_id"] == 12:
            raise RuntimeError("injected first notification failure")

    with patch.object(ApprovalNotificationService, "notify_user", side_effect=notify_user):
        result = await ApprovalDynamicAssigneeService.reconcile_instance(
            instance_id=instance.id,
            resolver=AsyncMock(return_value=[10, 12, 13]),
            trigger="permission_changed",
        )

    assert result.added_user_ids == (12, 13)
    assert notified_user_ids == [12, 13]


async def test_dynamic_task_notification_rechecks_pending_state_by_tenant(dynamic_db):
    instance, _ = await _seed_dynamic(approvers=(10,))
    async with ApprovalInstanceRepository.decision_session() as session:
        async with session.begin():
            result = await ApprovalDynamicAssigneeService.resolve_and_reconcile_in_uow(
                session=session,
                instance_id=instance.id,
                resolver=AsyncMock(return_value=[10, 12]),
                trigger="decision",
            )
            await ApprovalInstanceRepository.flush_decision_in_session(session)

    created = next(
        task for task in await ApprovalInstanceRepository.list_tasks(instance.id) if task.approver_user_id == 12
    )
    created.status = ApprovalTaskStatus.CANCELLED
    await ApprovalInstanceRepository.update_task(created)

    with patch.object(ApprovalNotificationService, "notify_user", new=AsyncMock()) as notify:
        await result.run_post_commit_effects()

    notify.assert_not_awaited()


async def test_removed_then_readded_user_gets_new_task_and_history_is_not_revived(dynamic_db):
    instance, original_tasks = await _seed_dynamic(approvers=(10, 11))
    with patch.object(ApprovalNotificationService, "notify_user", new=AsyncMock()):
        await ApprovalDynamicAssigneeService.reconcile_instance(
            instance_id=instance.id,
            resolver=AsyncMock(return_value=[11]),
            trigger="permission_changed",
        )
        await ApprovalDynamicAssigneeService.reconcile_instance(
            instance_id=instance.id,
            resolver=AsyncMock(return_value=[10, 11]),
            trigger="permission_changed",
        )

    tasks = await ApprovalInstanceRepository.list_tasks(instance.id)
    user_ten_tasks = [row for row in tasks if row.approver_user_id == 10]
    assert len(user_ten_tasks) == 2
    assert user_ten_tasks[0].id == original_tasks[0].id
    assert user_ten_tasks[0].status == ApprovalTaskStatus.CANCELLED
    assert user_ten_tasks[1].id != original_tasks[0].id
    assert user_ten_tasks[1].status == ApprovalTaskStatus.PENDING


async def test_repeated_and_serialized_concurrent_reconcile_is_idempotent(dynamic_db, monkeypatch):
    instance, _ = await _seed_dynamic(approvers=(10,))
    original_factory = ApprovalInstanceRepository.decision_session
    transaction_serialization = asyncio.Lock()

    @asynccontextmanager
    async def serialized_factory():
        async with transaction_serialization:
            async with original_factory() as session:
                yield session

    monkeypatch.setattr(ApprovalInstanceRepository, "decision_session", serialized_factory)
    resolver = AsyncMock(return_value=[10, 11])
    with patch.object(ApprovalNotificationService, "notify_user", new=AsyncMock()) as notify:
        first, second = await asyncio.gather(
            ApprovalDynamicAssigneeService.reconcile_instance(
                instance_id=instance.id,
                resolver=resolver,
                trigger="lazy_list",
            ),
            ApprovalDynamicAssigneeService.reconcile_instance(
                instance_id=instance.id,
                resolver=resolver,
                trigger="lazy_list",
            ),
        )

    tasks = await ApprovalInstanceRepository.list_tasks(instance.id)
    assert [(row.approver_user_id, row.status) for row in tasks] == [
        (10, ApprovalTaskStatus.PENDING),
        (11, ApprovalTaskStatus.PENDING),
    ]
    assert sorted((first.added_user_ids, second.added_user_ids)) == [(), (11,)]
    notify.assert_awaited_once()


async def test_empty_set_creates_one_open_exception_and_recovery_resolves_only_that_node(dynamic_db):
    instance, _ = await _seed_dynamic(approvers=(10,))
    with (
        patch.object(ApprovalNotificationService, "notify_user", new=AsyncMock()) as notify_user,
        patch.object(ApprovalNotificationService, "notify_admins", new=AsyncMock()) as notify_admins,
    ):
        first = await ApprovalDynamicAssigneeService.reconcile_instance(
            instance_id=instance.id,
            resolver=AsyncMock(return_value=[]),
            trigger="beat",
        )
        second = await ApprovalDynamicAssigneeService.reconcile_instance(
            instance_id=instance.id,
            resolver=AsyncMock(return_value=[]),
            trigger="beat",
        )
        recovered = await ApprovalDynamicAssigneeService.reconcile_instance(
            instance_id=instance.id,
            resolver=AsyncMock(return_value=[12]),
            trigger="lazy_list",
        )

    saved_instance, tasks, exceptions, _ = await _all_rows(instance.id)
    assert first.entered_approver_empty is True
    assert second.entered_approver_empty is False
    assert recovered.resolved_approver_empty is True
    assert saved_instance.status == ApprovalInstanceStatus.PENDING
    assert len(exceptions) == 1
    assert exceptions[0].status == "resolved"
    assert exceptions[0].resolved_by_user_id is None
    assert exceptions[0].resolved_action == "approvers_reconciled"
    assert [(row.approver_user_id, row.status) for row in tasks] == [
        (10, ApprovalTaskStatus.CANCELLED),
        (12, ApprovalTaskStatus.PENDING),
    ]
    notify_admins.assert_awaited_once()
    notify_user.assert_awaited_once()


async def test_strict_resolver_failure_leaves_tasks_instance_exception_and_logs_untouched(dynamic_db):
    instance, _ = await _seed_dynamic(approvers=(10,))
    resolver_error = RuntimeError("OpenFGA unavailable")
    with (
        patch.object(ApprovalNotificationService, "notify_user", new=AsyncMock()) as notify_user,
        patch.object(ApprovalNotificationService, "notify_admins", new=AsyncMock()) as notify_admins,
        pytest.raises(RuntimeError, match="OpenFGA unavailable"),
    ):
        await ApprovalDynamicAssigneeService.reconcile_instance(
            instance_id=instance.id,
            resolver=AsyncMock(side_effect=resolver_error),
            trigger="decision",
        )

    saved_instance, tasks, exceptions, logs = await _all_rows(instance.id)
    assert saved_instance.status == ApprovalInstanceStatus.PENDING
    assert [row.status for row in tasks] == [ApprovalTaskStatus.PENDING]
    assert exceptions == []
    assert logs == []
    notify_user.assert_not_awaited()
    notify_admins.assert_not_awaited()


async def test_failure_after_reconcile_flush_rolls_back_every_write_and_effect(dynamic_db, monkeypatch):
    instance, _ = await _seed_dynamic(approvers=(10,))
    original_flush = ApprovalInstanceRepository.flush_decision_in_session

    async def fail_after_flush(session):
        await original_flush(session)
        raise RuntimeError("injected reconciliation failure")

    monkeypatch.setattr(ApprovalInstanceRepository, "flush_decision_in_session", fail_after_flush)
    with (
        patch.object(ApprovalNotificationService, "notify_user", new=AsyncMock()) as notify_user,
        pytest.raises(RuntimeError, match="injected reconciliation failure"),
    ):
        await ApprovalDynamicAssigneeService.reconcile_instance(
            instance_id=instance.id,
            resolver=AsyncMock(return_value=[11]),
            trigger="decision",
        )

    saved_instance, tasks, exceptions, logs = await _all_rows(instance.id)
    assert saved_instance.status == ApprovalInstanceStatus.PENDING
    assert [(row.approver_user_id, row.status) for row in tasks] == [(10, ApprovalTaskStatus.PENDING)]
    assert exceptions == []
    assert logs == []
    notify_user.assert_not_awaited()
