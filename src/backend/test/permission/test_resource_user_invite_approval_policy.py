from __future__ import annotations

import inspect
from collections.abc import AsyncIterator
from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from bisheng.approval.domain.ports.decision_subscriber import (
    APPROVAL_DECISION_EVENT_VERSION,
    ApprovalDecisionEvent,
    ApprovalDecisionPermanentError,
    ApprovalDecisionRetryableError,
)
from bisheng.approval.domain.ports.scenario_policy import (
    ApprovalApplicant,
    ApprovalDecisionContext,
    ApprovalSubmissionCommand,
)
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.permission.domain.models.resource_user_invite_request import (
    ResourceUserInviteExecutionState,
    ResourceUserInviteRequest,
)
from bisheng.permission.domain.services import resource_user_invite_approval_policy as policy_module
from bisheng.permission.domain.services import resource_user_invite_decision_subscriber as subscriber_module
from bisheng.permission.domain.services.resource_user_invite_approval_policy import (
    ResourceUserInviteApprovalPolicy,
)
from bisheng.permission.domain.services.resource_user_invite_decision_subscriber import (
    ResourceUserInviteDecisionSubscriber,
)

TENANT_ID = 7
SCENARIO_CODE = "resource_user_invite_confirmation"
BUSINESS_REQUEST_TYPE = "resource_user_invite_request"


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(ResourceUserInviteRequest.__table__.create)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    tenant_token = set_current_tenant_id(TENANT_ID)
    try:
        yield factory
    finally:
        current_tenant_id.reset(tenant_token)
        await engine.dispose()


async def _create_request(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    approval_instance_id: int = 501,
    target_user_id: int = 201,
    request_fingerprint: str = "request-fingerprint",
) -> ResourceUserInviteRequest:
    async with session_factory() as session, session.begin():
        row = ResourceUserInviteRequest(
            tenant_id=TENANT_ID,
            business_key="resource-user-invite:knowledge_space:88:user:201",
            active_marker=0,
            request_fingerprint=request_fingerprint,
            resource_type="knowledge_space",
            resource_id="88",
            resource_name="Docs",
            inviter_user_id=101,
            inviter_user_name="inviter-a",
            target_user_id=target_user_id,
            target_user_name="target-a",
            relation="editor",
            model_id="model-1",
            include_children=True,
            role_snapshot={"permissions": ["read", "write"]},
            role_fingerprint="role-fingerprint",
            approval_instance_id=approval_instance_id,
            execution_state=ResourceUserInviteExecutionState.AWAITING_APPROVAL,
            result_snapshot={},
        )
        session.add(row)
        await session.flush()
        assert row.id is not None
    return row


async def _get_request(
    session_factory: async_sessionmaker[AsyncSession],
    request_id: int,
) -> ResourceUserInviteRequest:
    async with session_factory() as session:
        row = await session.get(ResourceUserInviteRequest, request_id)
    assert row is not None
    return row


def _submission_command(
    *,
    request_id: int = 1,
    target_user_id: int = 201,
    approver_user_ids: tuple[int, ...] | None = None,
) -> ApprovalSubmissionCommand:
    return ApprovalSubmissionCommand(
        tenant_id=TENANT_ID,
        scenario_code=SCENARIO_CODE,
        business_request_type=BUSINESS_REQUEST_TYPE,
        business_request_id=str(request_id),
        business_key="resource-user-invite:knowledge_space:88:user:201",
        request_fingerprint="request-fingerprint",
        title="Docs",
        applicant=ApprovalApplicant(user_id=101, user_name="inviter-a"),
        initial_approver_user_ids=approver_user_ids or (target_user_id,),
        detail_snapshot={
            "target_user_id": target_user_id,
            "target_user_name": "target-a",
            "resource_type": "knowledge_space",
            "resource_name": "Docs",
            "relation": "editor",
        },
        link_snapshot={"resource_type": "knowledge_space", "resource_id": "88"},
    )


def _decision_context(
    row: ResourceUserInviteRequest,
    *,
    operator_user_id: int = 201,
    tenant_id: int = TENANT_ID,
    approval_instance_id: int | None = None,
    business_request_type: str = BUSINESS_REQUEST_TYPE,
    business_request_id: str | None = None,
    request_fingerprint: str | None = None,
) -> ApprovalDecisionContext:
    return ApprovalDecisionContext(
        tenant_id=tenant_id,
        approval_instance_id=approval_instance_id or int(row.approval_instance_id),
        business_request_type=business_request_type,
        business_request_id=business_request_id or str(row.id),
        request_fingerprint=request_fingerprint or row.request_fingerprint,
        operator_user_id=operator_user_id,
        decision="approved",
    )


def _event(
    row: ResourceUserInviteRequest,
    *,
    event_id: int = 9001,
    decision: str = "approved",
    tenant_id: int = TENANT_ID,
    approval_instance_id: int | None = None,
    business_request_type: str = BUSINESS_REQUEST_TYPE,
    business_request_id: str | None = None,
    request_fingerprint: str | None = None,
) -> ApprovalDecisionEvent:
    return ApprovalDecisionEvent(
        event_id=event_id,
        event_version=APPROVAL_DECISION_EVENT_VERSION,
        decision_version=1,
        tenant_id=tenant_id,
        scenario_code=SCENARIO_CODE,
        approval_instance_id=approval_instance_id or int(row.approval_instance_id),
        business_request_type=business_request_type,
        business_request_id=business_request_id or str(row.id),
        business_key=row.business_key,
        request_fingerprint=request_fingerprint or row.request_fingerprint,
        decision=decision,
        decided_at=datetime(2026, 8, 13, 12, 0, 0),
        operator_user_id=row.target_user_id,
    )


class FakeDispatcher:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory
        self.calls: list[tuple[int, int]] = []
        self.states_seen: list[str] = []
        self.failures: list[Exception] = []

    async def dispatch(self, *, tenant_id: int, request_id: int) -> None:
        row = await _get_request(self.session_factory, request_id)
        self.states_seen.append(row.execution_state)
        self.calls.append((tenant_id, request_id))
        if self.failures:
            raise self.failures.pop(0)


async def test_policy_requires_the_invitee_as_the_only_or_approver(session_factory) -> None:
    policy = ResourceUserInviteApprovalPolicy(session_factory=session_factory)

    assert policy.node_mode == "or"
    await policy.validate_submission(_submission_command())

    for approvers in ((201, 202), (999,)):
        with pytest.raises(ApprovalDecisionPermanentError):
            await policy.validate_submission(_submission_command(approver_user_ids=approvers))


async def test_policy_rejects_admin_substitution_and_allows_only_invitee(session_factory) -> None:
    row = await _create_request(session_factory)
    policy = ResourceUserInviteApprovalPolicy(session_factory=session_factory)

    with pytest.raises(ApprovalDecisionPermanentError, match="invitee"):
        await policy.authorize_decision(_decision_context(row, operator_user_id=999))

    await policy.authorize_decision(_decision_context(row, operator_user_id=row.target_user_id))


@pytest.mark.parametrize(
    "overrides",
    [
        {"tenant_id": 8},
        {"approval_instance_id": 999},
        {"business_request_type": "knowledge_space_file_change_request"},
        {"business_request_id": "999"},
        {"request_fingerprint": "tampered"},
    ],
)
async def test_policy_rejects_invalid_business_binding_permanently(session_factory, overrides) -> None:
    row = await _create_request(session_factory)
    policy = ResourceUserInviteApprovalPolicy(session_factory=session_factory)

    with pytest.raises(ApprovalDecisionPermanentError):
        await policy.authorize_decision(_decision_context(row, **overrides))


async def test_approved_event_commits_queued_before_dispatch(session_factory) -> None:
    row = await _create_request(session_factory)
    dispatcher = FakeDispatcher(session_factory)
    subscriber = ResourceUserInviteDecisionSubscriber(
        session_factory=session_factory,
        dispatcher=dispatcher,
    )

    await subscriber.accept(_event(row))

    persisted = await _get_request(session_factory, int(row.id))
    assert persisted.execution_state == ResourceUserInviteExecutionState.QUEUED
    assert persisted.decision_event_id == 9001
    assert dispatcher.calls == [(TENANT_ID, int(row.id))]
    assert dispatcher.states_seen == [ResourceUserInviteExecutionState.QUEUED]


async def test_repeated_same_approved_event_is_idempotent_without_redispatch(session_factory) -> None:
    row = await _create_request(session_factory)
    dispatcher = FakeDispatcher(session_factory)
    subscriber = ResourceUserInviteDecisionSubscriber(
        session_factory=session_factory,
        dispatcher=dispatcher,
    )
    event = _event(row)

    await subscriber.accept(event)
    await subscriber.accept(event)

    assert dispatcher.calls == [(TENANT_ID, int(row.id))]
    persisted = await _get_request(session_factory, int(row.id))
    assert persisted.decision_event_id == event.event_id
    assert persisted.execution_state == ResourceUserInviteExecutionState.QUEUED


async def test_dispatcher_failure_keeps_queued_and_same_event_retries_dispatch(session_factory) -> None:
    row = await _create_request(session_factory)
    dispatcher = FakeDispatcher(session_factory)
    dispatcher.failures.append(RuntimeError("broker unavailable"))
    subscriber = ResourceUserInviteDecisionSubscriber(
        session_factory=session_factory,
        dispatcher=dispatcher,
    )
    event = _event(row)

    with pytest.raises(ApprovalDecisionRetryableError, match="broker unavailable"):
        await subscriber.accept(event)

    persisted = await _get_request(session_factory, int(row.id))
    assert persisted.execution_state == ResourceUserInviteExecutionState.QUEUED
    assert persisted.decision_event_id == event.event_id

    await subscriber.accept(event)
    await subscriber.accept(event)

    assert dispatcher.calls == [
        (TENANT_ID, int(row.id)),
        (TENANT_ID, int(row.id)),
    ]


@pytest.mark.parametrize("decision", ["rejected", "withdrawn", "cancelled"])
async def test_non_approved_terminal_event_closes_and_releases_active_marker(
    session_factory,
    decision,
) -> None:
    row = await _create_request(session_factory)
    dispatcher = FakeDispatcher(session_factory)
    subscriber = ResourceUserInviteDecisionSubscriber(
        session_factory=session_factory,
        dispatcher=dispatcher,
    )

    await subscriber.accept(_event(row, decision=decision))

    persisted = await _get_request(session_factory, int(row.id))
    assert persisted.execution_state == ResourceUserInviteExecutionState.CLOSED
    assert persisted.active_marker == row.id
    assert persisted.decision_event_id == 9001
    assert dispatcher.calls == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"tenant_id": 8},
        {"approval_instance_id": 999},
        {"business_request_type": "knowledge_space_file_change_request"},
        {"business_request_id": "999"},
        {"request_fingerprint": "tampered"},
    ],
)
async def test_subscriber_rejects_invalid_binding_without_mutation(session_factory, overrides) -> None:
    row = await _create_request(session_factory)
    dispatcher = FakeDispatcher(session_factory)
    subscriber = ResourceUserInviteDecisionSubscriber(
        session_factory=session_factory,
        dispatcher=dispatcher,
    )

    with pytest.raises(ApprovalDecisionPermanentError):
        await subscriber.accept(_event(row, **overrides))

    persisted = await _get_request(session_factory, int(row.id))
    assert persisted.execution_state == ResourceUserInviteExecutionState.AWAITING_APPROVAL
    assert persisted.decision_event_id is None
    assert dispatcher.calls == []


@pytest.mark.parametrize("second_event_id", [9000, 9002])
async def test_old_or_out_of_order_event_is_permanent_and_does_not_redispatch(
    session_factory,
    second_event_id,
) -> None:
    row = await _create_request(session_factory)
    dispatcher = FakeDispatcher(session_factory)
    subscriber = ResourceUserInviteDecisionSubscriber(
        session_factory=session_factory,
        dispatcher=dispatcher,
    )
    await subscriber.accept(_event(row, event_id=9001))

    with pytest.raises(ApprovalDecisionPermanentError, match="event"):
        await subscriber.accept(_event(row, event_id=second_event_id))

    assert dispatcher.calls == [(TENANT_ID, int(row.id))]


async def test_same_event_id_with_different_decision_is_permanent(session_factory) -> None:
    row = await _create_request(session_factory)
    dispatcher = FakeDispatcher(session_factory)
    subscriber = ResourceUserInviteDecisionSubscriber(
        session_factory=session_factory,
        dispatcher=dispatcher,
    )
    await subscriber.accept(_event(row, event_id=9001, decision="approved"))

    with pytest.raises(ApprovalDecisionPermanentError, match="event"):
        await subscriber.accept(_event(row, event_id=9001, decision="rejected"))

    assert dispatcher.calls == [(TENANT_ID, int(row.id))]


def test_policy_and_subscriber_do_not_import_approval_persistence() -> None:
    for module in (policy_module, subscriber_module):
        source = inspect.getsource(module)
        assert "approval.domain.models" not in source
        assert "approval.domain.repositories" not in source
