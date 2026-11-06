"""App business withdrawal is target-bound and atomic; generic applicant rules remain."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.approval.domain.models.approval_instance import ApprovalActionLog, ApprovalInstance, ApprovalTask
from bisheng.common.errcode.approval import ApprovalInstanceNotPendingError, ApprovalRequestPermissionDeniedError


@pytest.fixture
async def withdrawal():
    from bisheng.approval.domain.repositories.app_publish_withdrawal_repository import AppPublishWithdrawalRepository

    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        for model in (ApprovalInstance, ApprovalTask, ApprovalActionLog):
            await connection.run_sync(model.__table__.create)

    @asynccontextmanager
    async def factory():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    async with factory() as session:
        session.add(
            ApprovalInstance(
                id=7,
                tenant_id=3,
                scenario_code="app_publish_request",
                scenario_name="publish",
                handler_key="app_publish_request",
                business_key="deployment",
                business_resource_type="app",
                business_resource_id="target",
                business_name="app",
                applicant_user_id=81,
                applicant_user_name="owner",
                status="pending",
                payload_snapshot={
                    "app_id": "target",
                    "deployment_id": "deployment",
                    "version_id": "version",
                    "tenant_id": 3,
                },
            )
        )
        session.add(
            ApprovalTask(
                id=8,
                tenant_id=3,
                instance_id=7,
                flow_version_id=1,
                node_code="node",
                node_name="review",
                node_order=0,
                approver_user_id=99,
                approver_source_type="direct_user",
                node_mode="OR",
                status="pending",
            )
        )
        await session.commit()
    expected = {
        "tenant_id": 3,
        "app_id": "target",
        "deployment_id": "deployment",
        "version_id": "version",
        "instance_id": 7,
    }
    yield AppPublishWithdrawalRepository(factory), factory, expected
    await engine.dispose()


async def test_non_applicant_business_withdraw_has_one_atomic_terminal(withdrawal):
    repo, factory, expected = withdrawal
    instance, tasks = await repo.withdraw(
        expected,
        operator_user_id=42,
        operator_user_name="actual",
        reason="cancel",
        actor_metadata={"subject_type": "user", "subject_id": 42},
    )
    assert instance.status == "withdrawn" and tasks[0].status == "cancelled"
    async with factory() as session:
        logs = (await session.exec(select(ApprovalActionLog))).all()
        assert len(logs) == 1 and logs[0].operator_user_id == 42
    with pytest.raises(ApprovalInstanceNotPendingError):
        await repo.withdraw(
            expected, operator_user_id=42, operator_user_name="actual", reason="again", actor_metadata={}
        )
    async with factory() as session:
        assert len((await session.exec(select(ApprovalActionLog))).all()) == 1


async def test_wrong_frozen_version_has_no_partial_effect(withdrawal):
    repo, factory, expected = withdrawal
    with pytest.raises(ApprovalRequestPermissionDeniedError):
        await repo.withdraw(
            {**expected, "version_id": "other"},
            operator_user_id=42,
            operator_user_name="actual",
            reason="cancel",
            actor_metadata={},
        )
    async with factory() as session:
        assert (await session.get(ApprovalInstance, 7)).status == "pending"
        assert (await session.get(ApprovalTask, 8)).status == "pending"
        assert (await session.exec(select(ApprovalActionLog))).all() == []


async def test_other_scenarios_still_require_applicant(monkeypatch):
    from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository
    from bisheng.approval.domain.services.approval_center_service import ApprovalCenterService

    monkeypatch.setattr(
        ApprovalInstanceRepository,
        "get_instance",
        AsyncMock(return_value=SimpleNamespace(applicant_user_id=81, scenario_code="menu_access_request")),
    )
    with pytest.raises(PermissionError, match="applicant"):
        await ApprovalCenterService.withdraw_instance(instance_id=7, operator_user_id=42)
