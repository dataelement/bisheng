from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import Column, Integer, String, func
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.approval.domain.models.approval_instance import (
    ApprovalActionLog,
    ApprovalException,
    ApprovalExceptionType,
    ApprovalInstance,
    ApprovalInstanceStatus,
    ApprovalOutbox,
    ApprovalTask,
)
from bisheng.approval.domain.models.approval_scenario import (
    ApprovalFlowDefinition,
    ApprovalFlowVersion,
    ApprovalNodeDefinition,
    ApprovalRouteRule,
    ApprovalScenario,
)
from bisheng.approval.domain.ports.decision_subscriber import (
    APPROVAL_DECISION_EVENT_VERSION,
    APPROVAL_DECISION_SUBSCRIBER_PROTOCOL_VERSION,
    ApprovalDecisionEvent,
)
from bisheng.approval.domain.ports.scenario_policy import (
    APPROVAL_SCENARIO_POLICY_PROTOCOL_VERSION,
    DECISION_DELIVERY_COMPLETION_MODE,
    ApprovalApplicant,
    ApprovalDecisionContext,
    ApprovalSubmissionCommand,
)
from bisheng.approval.domain.services.approval_registry import ApprovalRegistry
from bisheng.approval.domain.services.approval_submission_service import ApprovalSubmissionService
from bisheng.common.errcode.approval import (
    ApprovalConfirmationFlowRequiredError,
    ApprovalScenarioDisabledError,
)
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id

TENANT_ID = 47
F045_SCENARIO = "resource_user_invite_confirmation"
F046_SCENARIO = "knowledge_space_file_change_request"


class _GuardSession:
    def __init__(self) -> None:
        self.transaction_active = False
        self.closed = False

    def begin(self):
        session = self

        class _Transaction:
            async def __aenter__(self):
                session.transaction_active = True

            async def __aexit__(self, exc_type, exc, traceback):
                session.transaction_active = False

        return _Transaction()


class _GuardRepository:
    scenario = SimpleNamespace(enabled=True)
    lock_calls: list[tuple[int, str]] = []

    @classmethod
    async def lock_submission_scenario_in_session(
        cls,
        session,
        *,
        tenant_id: int,
        scenario_code: str,
    ):
        assert session.transaction_active is True
        cls.lock_calls.append((tenant_id, scenario_code))
        return cls.scenario


def _guard_service(scenario):
    session = _GuardSession()
    _GuardRepository.scenario = scenario
    _GuardRepository.lock_calls = []

    @asynccontextmanager
    async def session_factory():
        try:
            yield session
        finally:
            session.closed = True

    return (
        ApprovalSubmissionService(
            registry=ApprovalRegistry(),
            repository=_GuardRepository,
            session_factory=session_factory,
        ),
        session,
    )


class BusinessRequestForSubmissionTest(SQLModel, table=True):
    __tablename__ = "business_request_for_submission_test"

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int = Field(sa_column=Column(Integer, nullable=False))
    request_type: str = Field(sa_column=Column(String(64), nullable=False))
    approval_instance_id: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))


@dataclass
class StubPolicy:
    scenario_code: str
    protocol_version: int = APPROVAL_SCENARIO_POLICY_PROTOCOL_VERSION
    completion_mode: str = DECISION_DELIVERY_COMPLETION_MODE
    validated_commands: list[ApprovalSubmissionCommand] = field(default_factory=list)

    async def validate_submission(self, command: ApprovalSubmissionCommand) -> None:
        self.validated_commands.append(command)

    async def authorize_decision(self, context: ApprovalDecisionContext) -> None:
        del context


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
async def submission_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [
        BusinessRequestForSubmissionTest.__table__,
        ApprovalScenario.__table__,
        ApprovalRouteRule.__table__,
        ApprovalFlowDefinition.__table__,
        ApprovalFlowVersion.__table__,
        ApprovalNodeDefinition.__table__,
        ApprovalInstance.__table__,
        ApprovalTask.__table__,
        ApprovalException.__table__,
        ApprovalActionLog.__table__,
        ApprovalOutbox.__table__,
    ]
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync_connection: SQLModel.metadata.create_all(sync_connection, tables=tables))
    yield engine
    await engine.dispose()


@pytest.fixture(autouse=True)
def submission_tenant_context():
    token = current_tenant_id.set(None)
    set_current_tenant_id(TENANT_ID)
    yield
    current_tenant_id.reset(token)


def _service(scenario_code: str) -> tuple[ApprovalSubmissionService, StubPolicy]:
    registry = ApprovalRegistry()
    policy = StubPolicy(scenario_code=scenario_code)
    subscriber = StubSubscriber(
        scenario_code=scenario_code,
        subscriber_key=f"{scenario_code}_subscriber",
    )
    registry.register_policy(policy)
    registry.register_subscriber(subscriber)
    registry.freeze_decision_delivery(required_scenario_codes={scenario_code})
    return ApprovalSubmissionService(registry=registry), policy


def _command(
    scenario_code: str,
    request_id: int,
    *,
    approver_user_ids: tuple[int, ...] = (101, 102),
) -> ApprovalSubmissionCommand:
    return ApprovalSubmissionCommand(
        tenant_id=TENANT_ID,
        scenario_code=scenario_code,
        business_request_type="test_business_request",
        business_request_id=str(request_id),
        business_key=f"test:{scenario_code}:{request_id}",
        request_fingerprint=f"fingerprint:{request_id}",
        title="Safe approval title",
        detail_snapshot={"action": "rename"},
        link_snapshot={"resource_id": "safe-id"},
        applicant=ApprovalApplicant(user_id=7, user_name="alice", department_id=8),
        initial_approver_user_ids=approver_user_ids,
    )


async def _seed_scenario(engine, scenario_code: str, *, route_type: str = "flow") -> None:
    async with AsyncSession(bind=engine, expire_on_commit=False) as session:
        async with session.begin():
            scenario = ApprovalScenario(
                tenant_id=TENANT_ID,
                scenario_code=scenario_code,
                scenario_name="Decision delivery scenario",
                enabled=True,
            )
            session.add(scenario)
            await session.flush()
            flow = ApprovalFlowDefinition(
                tenant_id=TENANT_ID,
                scenario_id=scenario.id,
                flow_code=f"{scenario_code}_flow",
                flow_name="Decision delivery flow",
            )
            session.add(flow)
            await session.flush()
            flow_version = ApprovalFlowVersion(
                tenant_id=TENANT_ID,
                flow_definition_id=flow.id,
                version_no=1,
                is_active=True,
                definition_snapshot={},
            )
            session.add(flow_version)
            await session.flush()
            session.add(
                ApprovalNodeDefinition(
                    tenant_id=TENANT_ID,
                    flow_version_id=flow_version.id,
                    node_code="business-approvers",
                    node_name="Business approvers",
                    node_order=1,
                    node_mode="or",
                    approver_config={"sources": [{"type": "business_policy"}]},
                )
            )
            session.add(
                ApprovalRouteRule(
                    tenant_id=TENANT_ID,
                    scenario_id=scenario.id,
                    route_name="Catch all",
                    route_type=route_type,
                    sort_order=1,
                    flow_definition_id=flow.id if route_type == "flow" else None,
                    match_config={},
                    enabled=True,
                )
            )


async def _count(session: AsyncSession, model: type[SQLModel]) -> int:
    return int((await session.exec(select(func.count()).select_from(model))).one())


async def test_submission_commits_business_binding_and_approval_bundle_together(submission_engine) -> None:
    await _seed_scenario(submission_engine, F045_SCENARIO)
    service, policy = _service(F045_SCENARIO)

    async with AsyncSession(bind=submission_engine, expire_on_commit=False) as session:
        async with session.begin():
            business_request = BusinessRequestForSubmissionTest(
                tenant_id=TENANT_ID,
                request_type=F045_SCENARIO,
            )
            session.add(business_request)
            await session.flush()
            command = _command(F045_SCENARIO, business_request.id)
            result = await service.submit_in_uow(session=session, command=command)
            business_request.approval_instance_id = result.instance_id
            session.add(business_request)

    async with AsyncSession(bind=submission_engine) as verification:
        saved_request = (await verification.exec(select(BusinessRequestForSubmissionTest))).one()
        instance = (await verification.exec(select(ApprovalInstance))).one()
        tasks = list((await verification.exec(select(ApprovalTask).order_by(ApprovalTask.id))).all())
        logs = list((await verification.exec(select(ApprovalActionLog))).all())

        assert saved_request.approval_instance_id == instance.id == result.instance_id
        assert instance.status == ApprovalInstanceStatus.PENDING
        assert instance.handler_key == f"{F045_SCENARIO}_subscriber"
        assert [task.approver_user_id for task in tasks] == [101, 102]
        assert [task.id for task in tasks] == list(result.task_ids)
        assert [log.action for log in logs] == ["submitted"]
        assert await _count(verification, ApprovalOutbox) == 0
    assert policy.validated_commands == [command]


async def test_submission_rolls_back_business_binding_and_entire_approval_bundle(submission_engine) -> None:
    await _seed_scenario(submission_engine, F046_SCENARIO)
    service, _ = _service(F046_SCENARIO)

    async with AsyncSession(bind=submission_engine, expire_on_commit=False) as session:
        with pytest.raises(RuntimeError, match="injected caller rollback"):
            async with session.begin():
                business_request = BusinessRequestForSubmissionTest(
                    tenant_id=TENANT_ID,
                    request_type=F046_SCENARIO,
                )
                session.add(business_request)
                await session.flush()
                result = await service.submit_in_uow(
                    session=session,
                    command=_command(F046_SCENARIO, business_request.id),
                )
                business_request.approval_instance_id = result.instance_id
                session.add(business_request)
                raise RuntimeError("injected caller rollback")

    async with AsyncSession(bind=submission_engine) as verification:
        assert await _count(verification, BusinessRequestForSubmissionTest) == 0
        assert await _count(verification, ApprovalInstance) == 0
        assert await _count(verification, ApprovalTask) == 0
        assert await _count(verification, ApprovalActionLog) == 0
        assert await _count(verification, ApprovalException) == 0
        assert await _count(verification, ApprovalOutbox) == 0


async def test_empty_initial_approvers_create_generic_approval_exception(submission_engine) -> None:
    await _seed_scenario(submission_engine, F046_SCENARIO)
    service, _ = _service(F046_SCENARIO)

    async with AsyncSession(bind=submission_engine, expire_on_commit=False) as session:
        async with session.begin():
            business_request = BusinessRequestForSubmissionTest(
                tenant_id=TENANT_ID,
                request_type=F046_SCENARIO,
            )
            session.add(business_request)
            await session.flush()
            result = await service.submit_in_uow(
                session=session,
                command=_command(F046_SCENARIO, business_request.id, approver_user_ids=()),
            )
            business_request.approval_instance_id = result.instance_id
            session.add(business_request)

    async with AsyncSession(bind=submission_engine) as verification:
        instance = (await verification.exec(select(ApprovalInstance))).one()
        exception = (await verification.exec(select(ApprovalException))).one()

        assert instance.id == result.instance_id
        assert instance.status == ApprovalInstanceStatus.EXCEPTION
        assert exception.instance_id == instance.id
        assert exception.exception_type == ApprovalExceptionType.APPROVER_EMPTY
        assert result.task_ids == ()
        assert await _count(verification, ApprovalTask) == 0
        assert await _count(verification, ApprovalActionLog) == 1
        assert await _count(verification, ApprovalOutbox) == 0


@pytest.mark.parametrize("scenario_code", [F045_SCENARIO, F046_SCENARIO])
async def test_decision_delivery_scenarios_reject_pass_routes(submission_engine, scenario_code: str) -> None:
    await _seed_scenario(submission_engine, scenario_code, route_type="pass")
    service, _ = _service(scenario_code)

    async with AsyncSession(bind=submission_engine) as session:
        with pytest.raises(ApprovalConfirmationFlowRequiredError):
            await service.submit_in_uow(
                session=session,
                command=_command(scenario_code, 123),
            )
        await session.rollback()

    async with AsyncSession(bind=submission_engine) as verification:
        assert await _count(verification, ApprovalInstance) == 0
        assert await _count(verification, ApprovalOutbox) == 0


async def test_submission_service_never_commits_caller_session(submission_engine) -> None:
    await _seed_scenario(submission_engine, F045_SCENARIO)
    service, _ = _service(F045_SCENARIO)

    async with AsyncSession(bind=submission_engine) as session:
        await session.begin()
        commit_spy = AsyncMock(side_effect=AssertionError("submission service committed caller session"))
        with patch.object(session, "commit", commit_spy):
            result = await service.submit_in_uow(
                session=session,
                command=_command(F045_SCENARIO, 123),
            )
        assert result.instance_id > 0
        commit_spy.assert_not_awaited()
        await session.rollback()


async def test_scenario_guard_holds_the_row_lock_transaction_until_exit() -> None:
    service, session = _guard_service(SimpleNamespace(enabled=True))

    async with service.scenario_guard(
        tenant_id=TENANT_ID,
        scenario_code=F045_SCENARIO,
    ):
        assert session.transaction_active is True
        assert session.closed is False

    assert _GuardRepository.lock_calls == [(TENANT_ID, F045_SCENARIO)]
    assert session.transaction_active is False
    assert session.closed is True


@pytest.mark.parametrize("scenario", [None, SimpleNamespace(enabled=False)])
async def test_scenario_guard_rejects_missing_or_disabled_scenario(scenario) -> None:
    service, session = _guard_service(scenario)

    with pytest.raises(ApprovalScenarioDisabledError):
        async with service.scenario_guard(
            tenant_id=TENANT_ID,
            scenario_code=F045_SCENARIO,
        ):
            raise AssertionError("disabled guard yielded")

    assert session.transaction_active is False
    assert session.closed is True


@pytest.mark.parametrize("error", [RuntimeError("business failed"), asyncio.CancelledError()])
async def test_scenario_guard_releases_transaction_on_error_or_cancellation(error) -> None:
    service, session = _guard_service(SimpleNamespace(enabled=True))

    with pytest.raises(type(error)):
        async with service.scenario_guard(
            tenant_id=TENANT_ID,
            scenario_code=F045_SCENARIO,
        ):
            raise error

    assert session.transaction_active is False
    assert session.closed is True
