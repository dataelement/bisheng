from __future__ import annotations

import inspect
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import bisheng.knowledge.domain.services.knowledge_space_file_change_approval_policy as policy_module
import bisheng.knowledge.domain.services.knowledge_space_file_change_decision_subscriber as subscriber_module
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
from bisheng.knowledge.domain.models.knowledge_space_file_change_request import (
    KnowledgeSpaceFileChangeAction,
    KnowledgeSpaceFileChangeCleanupState,
    KnowledgeSpaceFileChangeExecutionState,
    KnowledgeSpaceFileChangeRequest,
    KnowledgeSpaceFileChangeResourceType,
)
from bisheng.knowledge.domain.services.knowledge_space_file_change_approval_policy import (
    KnowledgeSpaceFileChangeApprovalPolicy,
)
from bisheng.knowledge.domain.services.knowledge_space_file_change_decision_subscriber import (
    KnowledgeSpaceFileChangeDecisionSubscriber,
)

TENANT_ID = 7
SCENARIO_CODE = "knowledge_space_file_change_request"
BUSINESS_REQUEST_TYPE = "knowledge_space_file_change_request"
REQUEST_FINGERPRINT = "file-change-request-fingerprint"
BUSINESS_KEY = "knowledge-space-change:1"


@pytest.fixture(autouse=True)
def tenant_context():
    tenant_token = set_current_tenant_id(TENANT_ID)
    try:
        yield
    finally:
        current_tenant_id.reset(tenant_token)


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(KnowledgeSpaceFileChangeRequest.__table__.create)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


async def _create_request(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    approval_instance_id: int = 501,
    request_fingerprint: str = REQUEST_FINGERPRINT,
    action: str = KnowledgeSpaceFileChangeAction.UPLOAD,
) -> KnowledgeSpaceFileChangeRequest:
    async with session_factory() as session, session.begin():
        row = KnowledgeSpaceFileChangeRequest(
            tenant_id=TENANT_ID,
            space_id=88,
            action=action,
            resource_type=(
                KnowledgeSpaceFileChangeResourceType.STAGED_UPLOAD
                if action == KnowledgeSpaceFileChangeAction.UPLOAD
                else KnowledgeSpaceFileChangeResourceType.KNOWLEDGE_FILE
            ),
            resource_id=None if action == KnowledgeSpaceFileChangeAction.UPLOAD else 301,
            applicant_user_id=101,
            approval_instance_id=approval_instance_id,
            upload_stage_id=41 if action == KnowledgeSpaceFileChangeAction.UPLOAD else None,
            file_name="report.pdf",
            business_key=BUSINESS_KEY,
            request_fingerprint=request_fingerprint,
            decision_event_id=None,
            execution_state=KnowledgeSpaceFileChangeExecutionState.NOT_STARTED,
            action_snapshot={"upload_id": "upload-opaque-1"},
            result_snapshot={},
            execution_checkpoint={},
        )
        session.add(row)
        await session.flush()
        assert row.id is not None
        row.business_key = f"knowledge-space-change:{row.id}"
    return row


async def _get_request(
    session_factory: async_sessionmaker[AsyncSession],
    request_id: int,
) -> KnowledgeSpaceFileChangeRequest:
    async with session_factory() as session:
        row = await session.get(KnowledgeSpaceFileChangeRequest, request_id)
    assert row is not None
    return row


def _submission_command(
    *,
    request_id: int = 1,
    initial_approver_user_ids: tuple[int, ...] = (201, 202),
    space_id: int = 88,
) -> ApprovalSubmissionCommand:
    return ApprovalSubmissionCommand(
        tenant_id=TENANT_ID,
        scenario_code=SCENARIO_CODE,
        business_request_type=BUSINESS_REQUEST_TYPE,
        business_request_id=str(request_id),
        business_key=f"knowledge-space-change:{request_id}",
        request_fingerprint=REQUEST_FINGERPRINT,
        title="Upload report.pdf",
        applicant=ApprovalApplicant(user_id=101, user_name="applicant"),
        initial_approver_user_ids=initial_approver_user_ids,
        detail_snapshot={"space_name": "Docs", "action": KnowledgeSpaceFileChangeAction.UPLOAD},
        link_snapshot={"space_id": space_id, "change_request_id": request_id},
    )


def _decision_context(
    row: KnowledgeSpaceFileChangeRequest,
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
    row: KnowledgeSpaceFileChangeRequest,
    *,
    event_id: int = 9001,
    decision: str = "approved",
    tenant_id: int = TENANT_ID,
    approval_instance_id: int | None = None,
    business_request_type: str = BUSINESS_REQUEST_TYPE,
    business_request_id: str | None = None,
    business_key: str | None = None,
    request_fingerprint: str | None = None,
    event_version: int = APPROVAL_DECISION_EVENT_VERSION,
    decision_version: int = 1,
) -> ApprovalDecisionEvent:
    return ApprovalDecisionEvent(
        event_id=event_id,
        event_version=event_version,
        decision_version=decision_version,
        tenant_id=tenant_id,
        scenario_code=SCENARIO_CODE,
        approval_instance_id=approval_instance_id or int(row.approval_instance_id),
        business_request_type=business_request_type,
        business_request_id=business_request_id or str(row.id),
        business_key=business_key or row.business_key,
        request_fingerprint=request_fingerprint or row.request_fingerprint,
        decision=decision,
        decided_at=datetime(2026, 8, 13, 12, 0, 0),
        operator_user_id=201,
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


class FakeTerminalCleanup:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory
        self.calls: list[tuple[int, int, str, str, str | None]] = []
        self.states_seen: list[str] = []
        self.failures: list[Exception] = []

    async def cleanup(
        self,
        *,
        tenant_id: int,
        request_id: int,
        upload_id: str,
        terminal_action: str,
        reason: str | None,
    ) -> None:
        row = await _get_request(self.session_factory, request_id)
        self.states_seen.append(row.execution_state)
        self.calls.append((tenant_id, request_id, upload_id, terminal_action, reason))
        async with self.session_factory() as session, session.begin():
            persisted = await session.get(KnowledgeSpaceFileChangeRequest, request_id)
            assert persisted is not None
            persisted.cleanup_state = KnowledgeSpaceFileChangeCleanupState.PENDING
        if self.failures:
            raise self.failures.pop(0)
        async with self.session_factory() as session, session.begin():
            persisted = await session.get(KnowledgeSpaceFileChangeRequest, request_id)
            assert persisted is not None
            persisted.cleanup_state = KnowledgeSpaceFileChangeCleanupState.SUCCESS


async def test_policy_resolves_strict_owner_manager_initial_approvers() -> None:
    resolver_calls: list[dict] = []

    async def resolve(**kwargs):
        resolver_calls.append(kwargs)
        return [202, 201, 202]

    policy = KnowledgeSpaceFileChangeApprovalPolicy(approver_resolver=resolve)
    await policy.validate_submission(_submission_command(initial_approver_user_ids=(201, 202)))

    assert resolver_calls == [
        {
            "tenant_id": TENANT_ID,
            "space_id": 88,
            "applicant_user_id": 101,
        }
    ]
    with pytest.raises(ApprovalDecisionPermanentError, match="approver"):
        await policy.validate_submission(_submission_command(initial_approver_user_ids=(201,)))


async def test_policy_rechecks_current_owner_manager_at_decision_time(session_factory) -> None:
    row = await _create_request(session_factory)
    resolver = AsyncMock(return_value=[201, 202])
    policy = KnowledgeSpaceFileChangeApprovalPolicy(
        session_factory=session_factory,
        approver_resolver=resolver,
    )

    await policy.authorize_decision(_decision_context(row, operator_user_id=201))
    with pytest.raises(ApprovalDecisionPermanentError, match="approver"):
        await policy.authorize_decision(_decision_context(row, operator_user_id=999))

    resolver.assert_awaited_with(
        tenant_id=TENANT_ID,
        space_id=88,
        applicant_user_id=None,
    )


async def test_policy_openfga_failure_is_fail_closed(session_factory) -> None:
    row = await _create_request(session_factory)

    async def unavailable(**_kwargs):
        raise RuntimeError("OpenFGA unavailable")

    policy = KnowledgeSpaceFileChangeApprovalPolicy(
        session_factory=session_factory,
        approver_resolver=unavailable,
    )

    with pytest.raises(RuntimeError, match="OpenFGA unavailable"):
        await policy.authorize_decision(_decision_context(row))

    with pytest.raises(RuntimeError, match="OpenFGA unavailable"):
        await policy.validate_submission(_submission_command(request_id=int(row.id)))


@pytest.mark.parametrize("field_name", ["business_key", "request_fingerprint"])
async def test_policy_rejects_empty_binding_security_field(field_name: str) -> None:
    command = replace(_submission_command(), **{field_name: ""})
    policy = KnowledgeSpaceFileChangeApprovalPolicy(approver_resolver=AsyncMock(return_value=[201, 202]))

    with pytest.raises(ApprovalDecisionPermanentError, match=field_name.replace("_", " ")):
        await policy.validate_submission(command)


@pytest.mark.parametrize("tenant_id", [None, 8])
async def test_policy_requires_matching_tenant_context(session_factory, tenant_id) -> None:
    row = await _create_request(session_factory)
    policy = KnowledgeSpaceFileChangeApprovalPolicy(
        session_factory=session_factory,
        approver_resolver=AsyncMock(return_value=[201]),
    )
    tenant_token = set_current_tenant_id(tenant_id)
    try:
        with pytest.raises(ApprovalDecisionPermanentError, match="tenant"):
            await policy.authorize_decision(_decision_context(row))
    finally:
        current_tenant_id.reset(tenant_token)


@pytest.mark.parametrize(
    "overrides",
    [
        {"tenant_id": 8},
        {"approval_instance_id": 999},
        {"business_request_type": "resource_user_invite_request"},
        {"business_request_id": "999"},
        {"request_fingerprint": "tampered"},
    ],
)
async def test_policy_rejects_invalid_binding_permanently(session_factory, overrides) -> None:
    row = await _create_request(session_factory)
    resolver = AsyncMock(return_value=[201])
    policy = KnowledgeSpaceFileChangeApprovalPolicy(
        session_factory=session_factory,
        approver_resolver=resolver,
    )

    with pytest.raises(ApprovalDecisionPermanentError):
        await policy.authorize_decision(_decision_context(row, **overrides))


async def test_approved_event_commits_queued_before_dispatch(session_factory) -> None:
    row = await _create_request(session_factory)
    dispatcher = FakeDispatcher(session_factory)
    cleanup = FakeTerminalCleanup(session_factory)
    subscriber = KnowledgeSpaceFileChangeDecisionSubscriber(
        session_factory=session_factory,
        dispatcher=dispatcher,
        terminal_cleanup=cleanup,
    )

    await subscriber.accept(_event(row))

    persisted = await _get_request(session_factory, int(row.id))
    assert persisted.execution_state == KnowledgeSpaceFileChangeExecutionState.QUEUED
    assert persisted.decision_event_id == 9001
    assert dispatcher.calls == [(TENANT_ID, int(row.id))]
    assert dispatcher.states_seen == [KnowledgeSpaceFileChangeExecutionState.QUEUED]
    assert cleanup.calls == []


async def test_repeated_approved_event_is_idempotent_without_redispatch(session_factory) -> None:
    row = await _create_request(session_factory)
    dispatcher = FakeDispatcher(session_factory)
    subscriber = KnowledgeSpaceFileChangeDecisionSubscriber(
        session_factory=session_factory,
        dispatcher=dispatcher,
        terminal_cleanup=FakeTerminalCleanup(session_factory),
    )
    event = _event(row)

    await subscriber.accept(event)
    await subscriber.accept(event)

    assert dispatcher.calls == [(TENANT_ID, int(row.id))]


async def test_repeated_dispatched_event_after_business_applied_is_idempotent(session_factory) -> None:
    row = await _create_request(session_factory)
    dispatcher = FakeDispatcher(session_factory)
    subscriber = KnowledgeSpaceFileChangeDecisionSubscriber(
        session_factory=session_factory,
        dispatcher=dispatcher,
        terminal_cleanup=FakeTerminalCleanup(session_factory),
    )
    event = _event(row)

    await subscriber.accept(event)
    async with session_factory() as session, session.begin():
        persisted = await session.get(KnowledgeSpaceFileChangeRequest, int(row.id))
        assert persisted is not None
        persisted.execution_state = KnowledgeSpaceFileChangeExecutionState.APPLIED
        session.add(persisted)

    await subscriber.accept(event)

    persisted = await _get_request(session_factory, int(row.id))
    assert persisted.execution_state == KnowledgeSpaceFileChangeExecutionState.APPLIED
    assert dispatcher.calls == [(TENANT_ID, int(row.id))]


async def test_dispatch_failure_keeps_queued_and_same_event_can_redispatch(session_factory) -> None:
    row = await _create_request(session_factory)
    dispatcher = FakeDispatcher(session_factory)
    dispatcher.failures.append(RuntimeError("knowledge broker unavailable"))
    subscriber = KnowledgeSpaceFileChangeDecisionSubscriber(
        session_factory=session_factory,
        dispatcher=dispatcher,
        terminal_cleanup=FakeTerminalCleanup(session_factory),
    )
    event = _event(row)

    with pytest.raises(ApprovalDecisionRetryableError, match="knowledge broker unavailable"):
        await subscriber.accept(event)

    persisted = await _get_request(session_factory, int(row.id))
    assert persisted.execution_state == KnowledgeSpaceFileChangeExecutionState.QUEUED
    assert persisted.decision_event_id == event.event_id

    await subscriber.accept(event)
    await subscriber.accept(event)
    assert dispatcher.calls == [(TENANT_ID, int(row.id)), (TENANT_ID, int(row.id))]


@pytest.mark.parametrize("decision", ["rejected", "withdrawn", "cancelled"])
async def test_non_approved_terminal_event_closes_then_runs_cleanup(
    session_factory,
    decision: str,
) -> None:
    row = await _create_request(session_factory)
    dispatcher = FakeDispatcher(session_factory)
    cleanup = FakeTerminalCleanup(session_factory)
    subscriber = KnowledgeSpaceFileChangeDecisionSubscriber(
        session_factory=session_factory,
        dispatcher=dispatcher,
        terminal_cleanup=cleanup,
    )

    await subscriber.accept(_event(row, decision=decision))

    persisted = await _get_request(session_factory, int(row.id))
    assert persisted.execution_state == KnowledgeSpaceFileChangeExecutionState.CLOSED
    assert persisted.decision_event_id == 9001
    assert dispatcher.calls == []
    assert cleanup.calls == [(TENANT_ID, int(row.id), "upload-opaque-1", decision, None)]
    assert cleanup.states_seen == [KnowledgeSpaceFileChangeExecutionState.CLOSED]


async def test_terminal_cleanup_failure_can_retry_same_event_without_duplicate_cleanup(
    session_factory,
) -> None:
    row = await _create_request(session_factory)
    cleanup = FakeTerminalCleanup(session_factory)
    cleanup.failures.append(RuntimeError("object storage unavailable"))
    subscriber = KnowledgeSpaceFileChangeDecisionSubscriber(
        session_factory=session_factory,
        dispatcher=FakeDispatcher(session_factory),
        terminal_cleanup=cleanup,
    )
    event = _event(row, decision="rejected")

    with pytest.raises(ApprovalDecisionRetryableError, match="object storage unavailable"):
        await subscriber.accept(event)

    persisted = await _get_request(session_factory, int(row.id))
    assert persisted.execution_state == KnowledgeSpaceFileChangeExecutionState.CLOSED
    assert persisted.decision_event_id == event.event_id
    assert persisted.cleanup_state == KnowledgeSpaceFileChangeCleanupState.PENDING

    await subscriber.accept(event)
    await subscriber.accept(event)

    persisted = await _get_request(session_factory, int(row.id))
    assert persisted.cleanup_state == KnowledgeSpaceFileChangeCleanupState.SUCCESS
    assert cleanup.calls == [
        (TENANT_ID, int(row.id), "upload-opaque-1", "rejected", None),
        (TENANT_ID, int(row.id), "upload-opaque-1", "rejected", None),
    ]
    assert cleanup.states_seen == [
        KnowledgeSpaceFileChangeExecutionState.CLOSED,
        KnowledgeSpaceFileChangeExecutionState.CLOSED,
    ]


@pytest.mark.parametrize(
    "overrides",
    [
        {"tenant_id": 8},
        {"approval_instance_id": 999},
        {"business_request_type": "resource_user_invite_request"},
        {"business_request_id": "999"},
        {"business_key": "tampered"},
        {"request_fingerprint": "tampered"},
        {"event_version": 999},
        {"decision_version": 2},
    ],
)
async def test_subscriber_rejects_invalid_event_without_mutation(session_factory, overrides) -> None:
    row = await _create_request(session_factory)
    dispatcher = FakeDispatcher(session_factory)
    cleanup = FakeTerminalCleanup(session_factory)
    subscriber = KnowledgeSpaceFileChangeDecisionSubscriber(
        session_factory=session_factory,
        dispatcher=dispatcher,
        terminal_cleanup=cleanup,
    )

    with pytest.raises(ApprovalDecisionPermanentError):
        await subscriber.accept(_event(row, **overrides))

    persisted = await _get_request(session_factory, int(row.id))
    assert persisted.execution_state == KnowledgeSpaceFileChangeExecutionState.NOT_STARTED
    assert persisted.decision_event_id is None
    assert dispatcher.calls == []
    assert cleanup.calls == []


@pytest.mark.parametrize("field_name", ["business_key", "request_fingerprint"])
async def test_subscriber_rejects_empty_binding_security_field(session_factory, field_name: str) -> None:
    row = await _create_request(session_factory)
    subscriber = KnowledgeSpaceFileChangeDecisionSubscriber(
        session_factory=session_factory,
        dispatcher=FakeDispatcher(session_factory),
        terminal_cleanup=FakeTerminalCleanup(session_factory),
    )

    with pytest.raises(ApprovalDecisionPermanentError, match=field_name.replace("_", " ")):
        await subscriber.accept(replace(_event(row), **{field_name: ""}))


def test_binding_security_columns_are_required_without_defaults() -> None:
    for column_name in ("business_key", "request_fingerprint"):
        column = KnowledgeSpaceFileChangeRequest.__table__.c[column_name]
        assert column.nullable is False
        assert column.default is None
        assert column.server_default is None


@pytest.mark.parametrize("tenant_id", [None, 8])
async def test_subscriber_requires_matching_tenant_context(session_factory, tenant_id) -> None:
    row = await _create_request(session_factory)
    subscriber = KnowledgeSpaceFileChangeDecisionSubscriber(
        session_factory=session_factory,
        dispatcher=FakeDispatcher(session_factory),
        terminal_cleanup=FakeTerminalCleanup(session_factory),
    )
    tenant_token = set_current_tenant_id(tenant_id)
    try:
        with pytest.raises(ApprovalDecisionPermanentError, match="tenant"):
            await subscriber.accept(_event(row))
    finally:
        current_tenant_id.reset(tenant_token)


@pytest.mark.parametrize("second_event_id", [9000, 9002])
async def test_old_or_out_of_order_event_is_permanent(session_factory, second_event_id: int) -> None:
    row = await _create_request(session_factory)
    dispatcher = FakeDispatcher(session_factory)
    subscriber = KnowledgeSpaceFileChangeDecisionSubscriber(
        session_factory=session_factory,
        dispatcher=dispatcher,
        terminal_cleanup=FakeTerminalCleanup(session_factory),
    )
    await subscriber.accept(_event(row, event_id=9001))

    with pytest.raises(ApprovalDecisionPermanentError, match="event"):
        await subscriber.accept(_event(row, event_id=second_event_id))

    assert dispatcher.calls == [(TENANT_ID, int(row.id))]


async def test_same_event_id_with_different_decision_is_permanent(session_factory) -> None:
    row = await _create_request(session_factory)
    dispatcher = FakeDispatcher(session_factory)
    subscriber = KnowledgeSpaceFileChangeDecisionSubscriber(
        session_factory=session_factory,
        dispatcher=dispatcher,
        terminal_cleanup=FakeTerminalCleanup(session_factory),
    )
    await subscriber.accept(_event(row, decision="approved"))

    with pytest.raises(ApprovalDecisionPermanentError, match="event"):
        await subscriber.accept(_event(row, decision="rejected"))


async def test_business_execution_failure_never_writes_approval(session_factory) -> None:
    row = await _create_request(session_factory)
    dispatcher = FakeDispatcher(session_factory)
    dispatcher.failures.append(RuntimeError("mutation worker unavailable"))
    subscriber = KnowledgeSpaceFileChangeDecisionSubscriber(
        session_factory=session_factory,
        dispatcher=dispatcher,
        terminal_cleanup=FakeTerminalCleanup(session_factory),
    )

    with pytest.raises(ApprovalDecisionRetryableError):
        await subscriber.accept(_event(row))

    for module in (policy_module, subscriber_module):
        source = inspect.getsource(module)
        assert "approval.domain.models" not in source
        assert "approval.domain.repositories" not in source
        assert "ApprovalInstance" not in source
        assert "ApprovalOutbox" not in source
        assert "ApprovalException" not in source


def test_policy_and_subscriber_depend_only_on_public_approval_ports() -> None:
    for module in (policy_module, subscriber_module):
        source = inspect.getsource(module)
        assert "bisheng.approval.domain.ports" in source
        assert "approval.domain.models" not in source
        assert "approval.domain.repositories" not in source
