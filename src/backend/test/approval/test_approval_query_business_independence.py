from __future__ import annotations

import asyncio
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
from bisheng.approval.domain.services.approval_registry import ApprovalRegistry
from bisheng.core.context.tenant import current_tenant_id
from bisheng.user.domain.models.user import UserDao

TENANT_ID = 42
F045_SCENARIO = "resource_user_invite_confirmation"
F046_SCENARIO = "knowledge_space_file_change_request"


@dataclass
class _Policy:
    scenario_code: str
    authorization_error: Exception | None = None
    protocol_version: int = APPROVAL_SCENARIO_POLICY_PROTOCOL_VERSION
    completion_mode: str = DECISION_DELIVERY_COMPLETION_MODE

    async def validate_submission(self, command: ApprovalSubmissionCommand) -> None:
        del command

    async def authorize_decision(self, context: ApprovalDecisionContext) -> None:
        del context
        if self.authorization_error is not None:
            raise self.authorization_error


@dataclass
class _Subscriber:
    scenario_code: str
    subscriber_key: str
    protocol_version: int = APPROVAL_DECISION_SUBSCRIBER_PROTOCOL_VERSION
    event_version: int = APPROVAL_DECISION_EVENT_VERSION
    completion_mode: str = DECISION_DELIVERY_COMPLETION_MODE

    async def accept(self, event: ApprovalDecisionEvent) -> None:
        del event


@pytest_asyncio.fixture
async def approval_query_db(monkeypatch: pytest.MonkeyPatch):
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

    decision_lock = asyncio.Lock()

    @asynccontextmanager
    async def session_factory():
        async with decision_lock:
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


def _registry(policy: _Policy) -> ApprovalRegistry:
    registry = ApprovalRegistry()
    registry.register_policy(policy)
    registry.register_subscriber(
        _Subscriber(
            scenario_code=policy.scenario_code,
            subscriber_key=f"{policy.scenario_code}_subscriber",
        )
    )
    registry.freeze_decision_delivery(required_scenario_codes={policy.scenario_code})
    return registry


async def _seed_instance(
    *,
    scenario_code: str,
    suffix: str,
    applicant_user_id: int = 7,
    approver_user_id: int = 9,
) -> tuple[ApprovalInstance, ApprovalTask]:
    instance = await ApprovalInstanceRepository.create_instance(
        ApprovalInstance(
            tenant_id=TENANT_ID,
            scenario_code=scenario_code,
            scenario_name="business-independent approval",
            handler_key=f"{scenario_code}_subscriber",
            business_key=f"business:{scenario_code}:{suffix}",
            business_resource_type="business_request",
            business_resource_id=suffix,
            business_name=f"request-{suffix}",
            applicant_user_id=applicant_user_id,
            applicant_user_name="applicant",
            flow_version_id=0,
            status=ApprovalInstanceStatus.PENDING,
            current_node_name="review",
            payload_snapshot={
                "completion_mode": DECISION_DELIVERY_COMPLETION_MODE,
                "business_request_type": "business_request",
                "business_request_id": suffix,
                "request_fingerprint": f"fingerprint:{suffix}",
                "target_user_id": approver_user_id,
                "safe_payload_label": f"payload-{suffix}",
            },
            detail_snapshot={"safe_detail_label": f"detail-{suffix}"},
        )
    )
    task = await ApprovalInstanceRepository.create_task(
        ApprovalTask(
            tenant_id=TENANT_ID,
            instance_id=int(instance.id),
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


@pytest.mark.parametrize("scenario_code", [F045_SCENARIO, F046_SCENARIO])
async def test_list_and_detail_use_only_approval_facts_when_business_domain_is_unavailable(
    approval_query_db,
    monkeypatch: pytest.MonkeyPatch,
    scenario_code: str,
) -> None:
    del approval_query_db
    instance, task = await _seed_instance(scenario_code=scenario_code, suffix=scenario_code)
    login_user = SimpleNamespace(user_id=9, tenant_id=TENANT_ID, is_admin=lambda: False)
    unavailable = AsyncMock(side_effect=RuntimeError("business domain unavailable"))
    monkeypatch.setattr(
        "bisheng.approval.domain.services.approval_center_service.build_runtime_handler",
        unavailable,
    )
    monkeypatch.setattr(UserDao, "aget_user_by_ids", AsyncMock(return_value=[]))

    task_list = await ApprovalCenterService.list_my_tasks(
        tenant_id=TENANT_ID,
        approver_user_id=9,
    )
    request_list = await ApprovalCenterService.list_my_requests(
        tenant_id=TENANT_ID,
        applicant_user_id=7,
    )
    task_detail = await ApprovalCenterService.get_task_detail(
        task_id=int(task.id),
        login_user=login_user,
    )
    instance_detail = await ApprovalCenterService.get_instance_detail(
        instance_id=int(instance.id),
        login_user=login_user,
    )

    assert task_list["data"][0]["scenario_code"] == scenario_code
    assert request_list["data"][0]["scenario_code"] == scenario_code
    for detail in (task_detail, instance_detail):
        assert detail["status"] == ApprovalInstanceStatus.PENDING
        if "instance_status" in detail:
            assert detail["instance_status"] == ApprovalInstanceStatus.PENDING
        assert detail["payload_snapshot"]["safe_payload_label"] == f"payload-{scenario_code}"
        assert detail["detail_snapshot"] == {"safe_detail_label": f"detail-{scenario_code}"}
        assert "business_status_projection" not in detail
    unavailable.assert_not_awaited()


def test_approval_query_code_has_no_permission_or_knowledge_dependency() -> None:
    query_methods = (
        ApprovalCenterService.list_my_tasks,
        ApprovalCenterService.list_my_requests,
        ApprovalCenterService.get_task_detail,
        ApprovalCenterService.get_instance_detail,
    )

    for method in query_methods:
        source = inspect.getsource(method)
        assert "bisheng.permission" not in source
        assert "bisheng.knowledge" not in source
        assert "build_runtime_handler" not in source


async def test_decision_qualification_failure_is_fail_closed(
    approval_query_db,
) -> None:
    instance, task = await _seed_instance(scenario_code=F046_SCENARIO, suffix="qualification-failure")
    policy = _Policy(
        scenario_code=F046_SCENARIO,
        authorization_error=RuntimeError("owner qualification unavailable"),
    )
    service = ApprovalCenterService(
        instance_repository=ApprovalInstanceRepository,
        registry=_registry(policy),
    )

    with pytest.raises(RuntimeError, match="owner qualification unavailable"):
        await service.decide_instance_for_current_approver(
            instance_id=int(instance.id),
            action="approve",
            operator_user_id=9,
            operator_user_name="reviewer",
            operator_tenant_id=TENANT_ID,
        )

    saved_instance = await ApprovalInstanceRepository.get_instance(int(instance.id))
    saved_task = await ApprovalInstanceRepository.get_task(int(task.id))
    async with AsyncSession(approval_query_db) as session:
        events = list((await session.exec(select(ApprovalDecisionOutbox))).all())
    assert saved_instance is not None and saved_instance.status == ApprovalInstanceStatus.PENDING
    assert saved_task is not None and saved_task.status == ApprovalTaskStatus.PENDING
    assert await ApprovalInstanceRepository.list_action_logs(int(instance.id)) == []
    assert events == []


async def test_batch_style_decisions_return_only_approval_terminal_facts(
    approval_query_db,
) -> None:
    del approval_query_db
    instances = [
        (await _seed_instance(scenario_code=F046_SCENARIO, suffix=f"batch-{index}"))[0]
        for index in range(2)
    ]
    service = ApprovalCenterService(
        instance_repository=ApprovalInstanceRepository,
        registry=_registry(_Policy(scenario_code=F046_SCENARIO)),
    )

    with (
        patch.object(ApprovalCenterService, "_write_audit_log", new=AsyncMock()),
        patch.object(ApprovalCenterService, "_send_approval_notify", new=AsyncMock()),
    ):
        results = [
            await service.decide_instance_for_current_approver(
                instance_id=int(instance.id),
                action="approve",
                operator_user_id=9,
                operator_user_name="reviewer",
                operator_tenant_id=TENANT_ID,
            )
            for instance in instances
        ]

    for result in results:
        assert set(result) == {"task_id", "instance_id", "status", "instance_status"}
        assert result["status"] == ApprovalTaskStatus.APPROVED
        assert result["instance_status"] == ApprovalInstanceStatus.APPROVED
