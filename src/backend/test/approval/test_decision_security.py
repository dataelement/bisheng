"""Security transitions against actual async SQL repository transactions.

SQLite verifies transaction behavior locally; it is not a live MySQL/DM8 run.
"""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.approval.api.endpoints.approval_user import ApprovalTaskDecisionReq
from bisheng.approval.domain.models.approval_instance import (
    ApprovalActionLog,
    ApprovalException,
    ApprovalInstance,
    ApprovalOutbox,
    ApprovalTask,
)
from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository as Repo
from bisheng.approval.domain.services.approval_center_service import ApprovalCenterService as Service
from bisheng.approval.domain.services.approval_outbox_service import ApprovalOutboxService
from bisheng.common.errcode.approval import ApprovalRequestAlreadyProcessedError

SCENARIOS = [
    "menu_access_request",
    "channel_subscribe_request",
    "knowledge_space_subscribe_request",
    "app_publish_request",
]


@pytest.fixture(autouse=True)
def decision_tenant(tenant_context):
    tenant_context(1)


@pytest.fixture
async def db(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/approval.db", connect_args={"timeout": 5})
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: SQLModel.metadata.create_all(
                c,
                tables=[
                    ApprovalInstance.__table__,
                    ApprovalTask.__table__,
                    ApprovalOutbox.__table__,
                    ApprovalActionLog.__table__,
                    ApprovalException.__table__,
                ],
            )
        )

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr(
        "bisheng.approval.domain.repositories.approval_instance_repository.get_async_db_session", sessions
    )
    monkeypatch.setattr(Service, "_write_audit_log", AsyncMock())
    monkeypatch.setattr(Service, "_send_approval_notify", AsyncMock())
    monkeypatch.setattr(Service, "_dispatch_outbox", Mock())
    monkeypatch.setattr("bisheng.approval.domain.services.approval_outbox_service.AuditLogDao.ainsert_v2", AsyncMock())
    monkeypatch.setattr(
        "bisheng.approval.domain.services.approval_notification_service.ApprovalNotificationService.notify_admins",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "bisheng.approval.domain.services.approval_runtime_handler_factory.eligible_scenario_candidates",
        AsyncMock(return_value=[11, 12]),
    )
    monkeypatch.setattr(
        "bisheng.approval.domain.services.approval_runtime_handler_factory.build_runtime_handler",
        AsyncMock(return_value=SimpleNamespace(on_rejected=AsyncMock())),
    )
    yield
    await engine.dispose()


async def seed(scenario="menu_access_request", mode="or", users=(11,)):
    instance = await Repo.create_instance(
        ApprovalInstance(
            tenant_id=1,
            scenario_code=scenario,
            scenario_name=scenario,
            handler_key=scenario,
            business_key="key",
            business_resource_type="test",
            business_resource_id="one",
            business_name="test",
            applicant_user_id=3,
            applicant_user_name="applicant",
            status="pending",
            payload_snapshot={},
            detail_snapshot={},
        )
    )
    tasks = []
    for user in users:
        tasks.append(
            await Repo.create_task(
                ApprovalTask(
                    tenant_id=1,
                    instance_id=instance.id,
                    flow_version_id=0,
                    node_code="n",
                    node_name="n",
                    node_order=1,
                    approver_user_id=user,
                    approver_source_type="direct_user",
                    node_mode=mode,
                    status="pending",
                )
            )
        )
    return instance, tasks


async def decide(task, action="approve"):
    await Service(instance_repository=Repo).decide_task(
        task_id=task.id,
        action=action,
        operator_user_id=task.approver_user_id,
        operator_user_name="approver",
        operator_tenant_id=1,
    )


@pytest.mark.parametrize("bad", ["aprove", "Approve", "ok", "", "reject ", None, 1])
def test_api_rejects_unknown_verdict(bad):
    with pytest.raises(ValidationError):
        ApprovalTaskDecisionReq(action=bad)


@pytest.mark.parametrize("scenario", SCENARIOS)
@pytest.mark.parametrize("bad", ["aprove", "Approve", "ok", "", "reject ", None])
async def test_service_rejects_unknown_without_effects(db, scenario, bad):
    instance, (task,) = await seed(scenario)
    with pytest.raises(HTTPException) as error:
        await decide(task, bad)
    assert error.value.status_code == 422
    assert (await Repo.get_task(task.id)).status == "pending"
    assert (await Repo.get_instance(instance.id)).status == "pending"
    assert await Repo.list_outbox(instance.id) == []
    Service._write_audit_log.assert_not_awaited()
    Service._dispatch_outbox.assert_not_called()


@pytest.mark.parametrize("scenario", SCENARIOS)
async def test_same_task_concurrent_has_one_finalization(db, scenario):
    instance, (task,) = await seed(scenario)
    results = await asyncio.gather(decide(task), decide(task), return_exceptions=True)
    assert sum(result is None for result in results) == 1
    assert sum(isinstance(result, ApprovalRequestAlreadyProcessedError) for result in results) == 1
    assert len(await Repo.list_outbox(instance.id)) == 1
    assert len(await Repo.list_action_logs(instance.id)) == 1
    Service._dispatch_outbox.assert_called_once()
    Service._send_approval_notify.assert_awaited_once()


@pytest.mark.parametrize("mode", ["or", "and"])
async def test_sibling_decisions_serialized(db, mode):
    instance, tasks = await seed(mode=mode, users=(11, 12))
    results = await asyncio.gather(*(decide(t) for t in tasks), return_exceptions=True)
    assert len(await Repo.list_outbox(instance.id)) == 1
    statuses = [t.status for t in await Repo.list_tasks(instance.id)]
    assert statuses.count("approved") == (2 if mode == "and" else 1)
    assert all(r is None or isinstance(r, ApprovalRequestAlreadyProcessedError) for r in results)
    Service._dispatch_outbox.assert_called_once()


async def test_failure_rolls_back_and_defers_all_effects(db, monkeypatch):
    instance, (task,) = await seed()

    async def fail(*_args, **_kwargs):
        raise RuntimeError("controlled before finalize")

    monkeypatch.setattr(Service, "_advance_after_node_approved", fail)
    with pytest.raises(RuntimeError):
        await decide(task)
    assert (await Repo.get_task(task.id)).status == "pending"
    assert (await Repo.get_instance(instance.id)).status == "pending"
    assert await Repo.list_action_logs(instance.id) == []
    assert await Repo.list_outbox(instance.id) == []
    Service._write_audit_log.assert_not_awaited()
    Service._dispatch_outbox.assert_not_called()


async def test_dispatch_reads_committed_state_and_failure_is_not_swallowed(db, monkeypatch):
    instance, (task,) = await seed()

    async def observe(outbox_id):
        assert (await Repo.get_outbox(outbox_id)).status == "pending"
        assert (await Repo.get_instance(instance.id)).status == "approved"
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr(Service, "_dispatch_outbox", observe)
    with pytest.raises(RuntimeError, match="queue unavailable"):
        await decide(task)
    assert len(await Repo.list_outbox(instance.id)) == 1
    with pytest.raises(ApprovalRequestAlreadyProcessedError):
        await decide(task)


async def test_outbox_concurrent_redelivery_and_success_replay(db):
    instance, (task,) = await seed()
    await decide(task)
    outbox = (await Repo.list_outbox(instance.id))[0]
    executor = AsyncMock(return_value=(True, None))
    service = ApprovalOutboxService(instance_repository=Repo)
    await asyncio.gather(*(service.execute_outbox(outbox_id=outbox.id, executor=executor) for _ in range(2)))
    assert await service.execute_outbox(outbox_id=outbox.id, executor=executor)
    executor.assert_awaited_once()
    assert (await Repo.get_outbox(outbox.id)).status == "success"


async def test_failed_requires_explicit_retry_and_claim_is_not_stolen(db):
    instance, (task,) = await seed()
    await decide(task)
    outbox = (await Repo.list_outbox(instance.id))[0]
    service = ApprovalOutboxService(instance_repository=Repo)
    executor = AsyncMock(return_value=(False, "controlled failure"))
    assert not await service.execute_outbox(outbox_id=outbox.id, executor=executor)
    assert not await service.execute_outbox(outbox_id=outbox.id, executor=executor)
    executor.assert_awaited_once()
    executor.return_value = (True, None)
    assert await service.retry_outbox(outbox_id=outbox.id, executor=executor)
    assert executor.await_count == 2
    # Simulate a worker lost after persisting ownership, before acknowledging effects.
    other_instance, _ = await seed()
    other_instance.status = "approved"
    await Repo.update_instance(other_instance)
    other = await Repo.create_outbox(
        ApprovalOutbox(tenant_id=1, instance_id=other_instance.id, handler_key="test", status="pending")
    )
    assert await Repo.claim_outbox(other.id)
    assert not await service.execute_outbox(outbox_id=other.id, executor=executor)
    assert not await service.retry_outbox(outbox_id=other.id, executor=executor)
    assert executor.await_count == 2
    claimed = await Repo.get_outbox(other.id)
    assert claimed.status == "executing" and "uncertain" in claimed.error_summary


async def test_distinct_old_duplicate_outboxes_do_not_both_execute(db):
    instance, (task,) = await seed()
    await decide(task)
    first = (await Repo.list_outbox(instance.id))[0]
    second = await Repo.create_outbox(
        ApprovalOutbox(tenant_id=1, instance_id=instance.id, handler_key="test", status="pending")
    )
    executor = AsyncMock(return_value=(True, None))
    service = ApprovalOutboxService(instance_repository=Repo)
    await asyncio.gather(*(service.execute_outbox(outbox_id=row.id, executor=executor) for row in [first, second]))
    executor.assert_awaited_once()


async def test_management_detail_exposes_uncertain_execution_without_payload(db, monkeypatch):
    instance, (task,) = await seed()
    await decide(task)
    outbox = (await Repo.list_outbox(instance.id))[0]
    await Repo.claim_outbox(outbox.id)
    monkeypatch.setattr(
        "bisheng.approval.domain.services.approval_center_service.UserDao.aget_user_by_ids", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        "bisheng.approval.domain.services.approval_center_service.read_current_scenario_detail",
        AsyncMock(return_value={}),
    )
    user = SimpleNamespace(user_id=99, tenant_id=1, is_global_super=True, is_admin=lambda: True)
    detail = await Service.get_instance_detail(instance_id=instance.id, login_user=user, management=True)
    execution = detail["executions"][0]
    assert execution["status"] == "executing"
    assert "uncertain" in execution["error_summary"]
    assert "payload_snapshot" not in execution


async def test_pending_duplicate_cannot_retry_failed_sibling(db):
    instance, (task,) = await seed()
    await decide(task)
    first = (await Repo.list_outbox(instance.id))[0]
    second = await Repo.create_outbox(
        ApprovalOutbox(tenant_id=1, instance_id=instance.id, handler_key="test", status="pending")
    )
    executor = AsyncMock(return_value=(False, "controlled failure"))
    service = ApprovalOutboxService(instance_repository=Repo)
    assert not await service.execute_outbox(outbox_id=first.id, executor=executor)
    assert not await service.execute_outbox(outbox_id=second.id, executor=executor)
    executor.assert_awaited_once()


@pytest.mark.parametrize("success", [True, False])
async def test_outbox_result_does_not_resurrect_cancelled_instance(db, success):
    instance, (task,) = await seed()
    await decide(task)
    outbox = (await Repo.list_outbox(instance.id))[0]

    async def executor(claimed):
        await Service.cancel_instance_by_business(instance_id=instance.id)
        return success, None if success else "controlled failure"

    service = ApprovalOutboxService(instance_repository=Repo)
    await service.execute_outbox(outbox_id=outbox.id, executor=executor)
    assert (await Repo.get_instance(instance.id)).status == "cancelled"
    assert await Repo.list_exceptions(instance.id) == []
    replay = AsyncMock(return_value=(True, None))
    await service.retry_outbox(outbox_id=outbox.id, executor=replay)
    replay.assert_not_awaited()


async def test_decision_racing_withdrawal_has_one_terminal_transition(db, monkeypatch):
    instance, (task,) = await seed()
    monkeypatch.setattr(Service, "_after_withdrawal", AsyncMock(return_value={}))
    results = await asyncio.gather(
        decide(task),
        Service.withdraw_instance(instance_id=instance.id, operator_user_id=instance.applicant_user_id),
        return_exceptions=True,
    )
    final = await Repo.get_instance(instance.id)
    assert final.status in ("approved", "withdrawn")
    assert len(await Repo.list_action_logs(instance.id)) == 1
    assert len(await Repo.list_outbox(instance.id)) == (1 if final.status == "approved" else 0)
    assert sum(isinstance(result, Exception) for result in results) == 1


async def test_setup_failure_after_cancel_does_not_revive_instance(db):
    instance, (task,) = await seed()
    await decide(task)
    outbox = (await Repo.list_outbox(instance.id))[0]
    await Service.cancel_instance_by_business(instance_id=instance.id)
    assert await Repo.fail_pending_outbox(outbox.id, "controlled setup failure")
    assert (await Repo.get_instance(instance.id)).status == "cancelled"
    assert await Repo.list_exceptions(instance.id) == []


async def test_admin_cancel_and_manual_complete_do_not_revive_terminal(db, monkeypatch):
    from bisheng.approval.domain.services.approval_exception_service import ApprovalExceptionService

    instance, (task,) = await seed()
    await decide(task)
    outbox = (await Repo.list_outbox(instance.id))[0]
    await ApprovalOutboxService(instance_repository=Repo).execute_outbox(
        outbox_id=outbox.id, executor=lambda row: (False, "controlled failure")
    )
    exception = (await Repo.list_exceptions(instance.id))[0]
    monkeypatch.setattr(ApprovalExceptionService, "_lookup_user_name", AsyncMock(return_value="admin"))
    monkeypatch.setattr(ApprovalExceptionService, "_write_audit_log", AsyncMock())
    monkeypatch.setattr(ApprovalExceptionService, "_notify_user", AsyncMock())
    await ApprovalExceptionService.cancel_exception_api(exception_id=exception.id, operator_user_id=99, reason="cancel")
    assert (await Repo.get_instance(instance.id)).status == "cancelled"
    with pytest.raises(ValueError):
        await ApprovalExceptionService(instance_repository=Repo).mark_manually_completed(
            exception_id=exception.id, resolved_by_user_id=99
        )
    assert (await Repo.get_instance(instance.id)).status == "cancelled"


async def test_withdrawal_transaction_failure_rolls_back_tasks_and_instance(db, monkeypatch):
    from bisheng.approval.domain.repositories.approval_instance_repository import _DecisionRepository

    instance, (task,) = await seed()
    after = AsyncMock()
    monkeypatch.setattr(Service, "_after_withdrawal", after)
    monkeypatch.setattr(
        _DecisionRepository, "create_action_log", AsyncMock(side_effect=RuntimeError("controlled rollback"))
    )
    with pytest.raises(RuntimeError, match="controlled rollback"):
        await Service.withdraw_instance(instance_id=instance.id, operator_user_id=instance.applicant_user_id)
    assert (await Repo.get_instance(instance.id)).status == "pending"
    assert (await Repo.get_task(task.id)).status == "pending"
    assert await Repo.list_action_logs(instance.id) == []
    after.assert_not_awaited()
