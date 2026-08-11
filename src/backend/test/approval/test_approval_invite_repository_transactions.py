from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta

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
    ApprovalOutboxStatus,
    ApprovalTask,
    ApprovalTaskStatus,
)
from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository
from bisheng.core.context.tenant import current_tenant_id


def _instance(*, applicant: int = 7, status: str = ApprovalInstanceStatus.PENDING):
    return ApprovalInstance(
        tenant_id=1,
        scenario_code="resource_user_invite_confirmation",
        scenario_name="知识空间用户邀请确认",
        handler_key="resource_user_invite_confirmation",
        business_key="resource-user-invite:knowledge_space:88:user:9",
        business_resource_type="knowledge_space",
        business_resource_id="88",
        business_name="docs",
        applicant_user_id=applicant,
        applicant_user_name="alice",
        flow_version_id=1,
        status=status,
        payload_snapshot={"target_user_id": 9},
        detail_snapshot={},
    )


@pytest_asyncio.fixture
async def invite_repo_db(monkeypatch):
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
        "bisheng.approval.domain.repositories.approval_instance_repository.get_async_db_session", factory
    )
    tenant_token = current_tenant_id.set(1)
    try:
        yield
    finally:
        current_tenant_id.reset(tenant_token)
        await engine.dispose()


async def test_find_blocking_invite_ignores_applicant(invite_repo_db):
    row = await ApprovalInstanceRepository.create_instance(_instance(applicant=7))

    found = await ApprovalInstanceRepository.find_blocking_invite(
        tenant_id=1,
        business_key=row.business_key,
    )

    assert found is not None
    assert found.applicant_user_id == 7


async def test_create_bundle_rolls_back_together(invite_repo_db):
    instance = _instance()
    task = ApprovalTask(
        tenant_id=1,
        instance_id=0,
        flow_version_id=1,
        node_code="invitee_confirm",
        node_name="被邀请用户确认",
        node_order=0,
        approver_user_id=9,
        approver_source_type="invited_user",
        node_mode="or",
        status=ApprovalTaskStatus.PENDING,
    )
    action_log = ApprovalActionLog(tenant_id=1, instance_id=0, action="submitted", detail={})

    saved, tasks, log = await ApprovalInstanceRepository.create_instance_bundle(
        instance=instance,
        tasks=[task],
        action_log=action_log,
    )

    assert saved.id and tasks[0].instance_id == saved.id and log.instance_id == saved.id


async def test_decide_single_task_accepts_one_terminal(invite_repo_db):
    _instance_row, tasks, _ = await ApprovalInstanceRepository.create_instance_bundle(
        instance=_instance(),
        tasks=[
            ApprovalTask(
                tenant_id=1,
                instance_id=0,
                flow_version_id=1,
                node_code="invitee_confirm",
                node_name="被邀请用户确认",
                node_order=0,
                approver_user_id=9,
                approver_source_type="invited_user",
                node_mode="or",
                status=ApprovalTaskStatus.PENDING,
            )
        ],
        action_log=ApprovalActionLog(tenant_id=1, instance_id=0, action="submitted", detail={}),
    )

    accepted = await ApprovalInstanceRepository.decide_single_task(
        task_id=tasks[0].id,
        operator_user_id=9,
        action="approve",
        operator_user_name="bob",
        comment=None,
    )
    repeated = await ApprovalInstanceRepository.decide_single_task(
        task_id=tasks[0].id,
        operator_user_id=9,
        action="reject",
        operator_user_name="bob",
        comment="no",
    )

    assert accepted is not None and accepted.instance.status == ApprovalInstanceStatus.APPROVED
    assert accepted.outbox is not None
    assert repeated is None


async def test_withdraw_pending_only(invite_repo_db):
    instance = await ApprovalInstanceRepository.create_instance(_instance())
    first = await ApprovalInstanceRepository.withdraw_pending_instance(
        instance_id=instance.id,
        applicant_user_id=7,
        operator_user_name="alice",
        reason=None,
    )
    second = await ApprovalInstanceRepository.withdraw_pending_instance(
        instance_id=instance.id,
        applicant_user_id=7,
        operator_user_name="alice",
        reason=None,
    )
    assert first is not None
    assert first.status == ApprovalInstanceStatus.WITHDRAWN
    assert second is None


async def test_claim_outbox_once_and_reclaim_after_ttl(invite_repo_db):
    instance = await ApprovalInstanceRepository.create_instance(_instance(status=ApprovalInstanceStatus.APPROVED))
    outbox = await ApprovalInstanceRepository.create_outbox(
        ApprovalOutbox(
            tenant_id=1,
            instance_id=instance.id,
            handler_key=instance.handler_key,
            status=ApprovalOutboxStatus.PENDING,
            payload_snapshot={},
        )
    )
    claimed = await ApprovalInstanceRepository.claim_outbox(outbox_id=outbox.id, claim_ttl_seconds=1200)
    duplicate = await ApprovalInstanceRepository.claim_outbox(outbox_id=outbox.id, claim_ttl_seconds=1200)
    current = await ApprovalInstanceRepository.get_outbox(outbox.id)
    current.update_time = datetime.utcnow() - timedelta(seconds=1201)
    await ApprovalInstanceRepository.update_outbox(current)
    reclaimed = await ApprovalInstanceRepository.claim_outbox(outbox_id=outbox.id, claim_ttl_seconds=1200)

    assert claimed is not None
    assert duplicate is None
    assert reclaimed is not None


async def test_finalize_outbox_success_commits_both_terminals(invite_repo_db):
    instance = await ApprovalInstanceRepository.create_instance(_instance(status=ApprovalInstanceStatus.APPROVED))
    outbox = await ApprovalInstanceRepository.create_outbox(
        ApprovalOutbox(
            tenant_id=1,
            instance_id=instance.id,
            handler_key=instance.handler_key,
            status=ApprovalOutboxStatus.PENDING,
            payload_snapshot={},
        )
    )
    await ApprovalInstanceRepository.claim_outbox(outbox_id=outbox.id, claim_ttl_seconds=1200)

    saved_outbox, saved_instance = await ApprovalInstanceRepository.finalize_outbox_success(outbox_id=outbox.id)

    assert saved_outbox.status == ApprovalOutboxStatus.SUCCESS
    assert saved_instance.status == ApprovalInstanceStatus.EXECUTED


async def test_finalize_outbox_failure_commits_instance_and_exception(invite_repo_db):
    instance = await ApprovalInstanceRepository.create_instance(_instance(status=ApprovalInstanceStatus.APPROVED))
    outbox = await ApprovalInstanceRepository.create_outbox(
        ApprovalOutbox(
            tenant_id=1,
            instance_id=instance.id,
            handler_key=instance.handler_key,
            status=ApprovalOutboxStatus.PENDING,
            payload_snapshot={},
        )
    )
    await ApprovalInstanceRepository.claim_outbox(outbox_id=outbox.id, claim_ttl_seconds=1200)

    saved_outbox, saved_instance = await ApprovalInstanceRepository.finalize_outbox_failure(
        outbox_id=outbox.id,
        error_summary="grant failed",
    )
    exceptions = await ApprovalInstanceRepository.list_exceptions(instance.id)

    assert saved_outbox.status == ApprovalOutboxStatus.FAILED
    assert saved_instance.status == ApprovalInstanceStatus.EXECUTE_FAILED
    assert len(exceptions) == 1
    assert exceptions[0].detail == {"error_summary": "grant failed"}


async def test_setup_failure_does_not_overwrite_processing_or_success(invite_repo_db):
    for index, (outbox_status, instance_status) in enumerate(
        (
            (ApprovalOutboxStatus.PROCESSING, ApprovalInstanceStatus.EXECUTING),
            (ApprovalOutboxStatus.SUCCESS, ApprovalInstanceStatus.EXECUTED),
        ),
        start=1,
    ):
        instance = _instance(status=instance_status)
        instance.business_key = f"resource-user-invite:knowledge_space:{index}:user:9"
        instance = await ApprovalInstanceRepository.create_instance(instance)
        outbox = await ApprovalInstanceRepository.create_outbox(
            ApprovalOutbox(
                tenant_id=1,
                instance_id=instance.id,
                handler_key=instance.handler_key,
                status=outbox_status,
                payload_snapshot={},
            )
        )

        recorded = await ApprovalInstanceRepository.record_outbox_setup_failure(
            outbox_id=outbox.id,
            error_summary="stale worker setup failed",
        )

        saved_outbox = await ApprovalInstanceRepository.get_outbox(outbox.id)
        saved_instance = await ApprovalInstanceRepository.get_instance(instance.id)
        exceptions = await ApprovalInstanceRepository.list_exceptions(instance.id)
        assert recorded is False
        assert saved_outbox.status == outbox_status
        assert saved_instance.status == instance_status
        assert exceptions == []
