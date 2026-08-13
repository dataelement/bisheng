from __future__ import annotations

from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import pytest

from bisheng.approval.domain.models.approval_decision_outbox import (
    ApprovalDecisionFailureKind,
    ApprovalDecisionOutbox,
    ApprovalDecisionOutboxStatus,
)
from bisheng.approval.domain.ports.decision_subscriber import (
    APPROVAL_DECISION_EVENT_VERSION,
    APPROVAL_DECISION_SUBSCRIBER_PROTOCOL_VERSION,
    ApprovalDecisionEvent,
    ApprovalDecisionPermanentError,
    ApprovalDecisionRetryableError,
)
from bisheng.approval.domain.ports.scenario_policy import DECISION_DELIVERY_COMPLETION_MODE
from bisheng.approval.domain.services.approval_decision_delivery_service import (
    ApprovalDecisionDeliveryService,
)
from bisheng.approval.domain.services.approval_registry import ApprovalRegistry
from bisheng.core.context.tenant import current_tenant_id

TENANT_ID = 42
SCENARIO_CODE = "resource_user_invite_confirmation"
NOW = datetime(2026, 8, 13, 10, 0, 0)
LEASE_DURATION = timedelta(minutes=5)
RETRY_DELAY = timedelta(seconds=30)


class _Clock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


class _TokenFactory:
    def __init__(self) -> None:
        self.sequence = 0

    def __call__(self) -> str:
        self.sequence += 1
        return f"claim-{self.sequence}"


class _FakeSession:
    def __init__(self, timeline: list[str]) -> None:
        self.timeline = timeline
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1
        self.timeline.append("approval.commit")

    async def rollback(self) -> None:
        self.rollbacks += 1
        self.timeline.append("approval.rollback")


class _DecisionStore:
    def __init__(self, rows: list[ApprovalDecisionOutbox]) -> None:
        self.rows = {int(row.id): row for row in rows}
        self.initial_event_ids = tuple(sorted(self.rows))
        self.approval_terminal_statuses = {int(row.instance_id): str(row.decision) for row in rows}
        self.ack_errors: list[Exception] = []
        self.sessions: list[_FakeSession] = []
        self.timeline: list[str] = []

    @asynccontextmanager
    async def session_factory(self):
        session = _FakeSession(self.timeline)
        self.sessions.append(session)
        yield session

    def repository_factory(self, _session: _FakeSession):
        return _FakeDecisionRepository(self)


class _FakeDecisionRepository:
    def __init__(self, store: _DecisionStore) -> None:
        self.store = store

    async def claim_next(
        self,
        *,
        tenant_id: int,
        claim_token: str,
        now: datetime,
        claim_deadline: datetime,
    ) -> ApprovalDecisionOutbox | None:
        for row in sorted(self.store.rows.values(), key=lambda item: int(item.id)):
            if int(row.tenant_id) != int(tenant_id):
                continue
            pending_due = row.status == ApprovalDecisionOutboxStatus.PENDING and (
                row.next_retry_at is None or row.next_retry_at <= now
            )
            lease_expired = (
                row.status == ApprovalDecisionOutboxStatus.PROCESSING
                and row.claim_deadline is not None
                and row.claim_deadline <= now
            )
            if not pending_due and not lease_expired:
                continue
            row.status = ApprovalDecisionOutboxStatus.PROCESSING
            row.claim_token = claim_token
            row.claimed_at = now
            row.claim_deadline = claim_deadline
            row.next_retry_at = None
            self.store.timeline.append(f"approval.claim:{row.id}")
            return row
        return None

    async def mark_delivered(
        self,
        *,
        tenant_id: int,
        outbox_id: int,
        claim_token: str,
    ) -> bool:
        self.store.timeline.append(f"approval.ack:{outbox_id}")
        if self.store.ack_errors:
            raise self.store.ack_errors.pop(0)
        row = self.store.rows[outbox_id]
        if int(row.tenant_id) != int(tenant_id) or row.claim_token != claim_token:
            return False
        if row.status not in (
            ApprovalDecisionOutboxStatus.PROCESSING,
            ApprovalDecisionOutboxStatus.DELIVERED,
        ):
            return False
        row.status = ApprovalDecisionOutboxStatus.DELIVERED
        row.failure_kind = None
        row.error_summary = None
        row.next_retry_at = None
        return True

    async def mark_retryable_failure(
        self,
        *,
        tenant_id: int,
        outbox_id: int,
        claim_token: str,
        error_summary: str,
        next_retry_at: datetime,
    ) -> bool:
        self.store.timeline.append(f"approval.retry:{outbox_id}")
        row = self.store.rows[outbox_id]
        if (
            int(row.tenant_id) != int(tenant_id)
            or row.status != ApprovalDecisionOutboxStatus.PROCESSING
            or row.claim_token != claim_token
        ):
            return False
        row.status = ApprovalDecisionOutboxStatus.PENDING
        row.claim_token = None
        row.claimed_at = None
        row.claim_deadline = None
        row.retry_count += 1
        row.error_summary = error_summary
        row.next_retry_at = next_retry_at
        row.failure_kind = ApprovalDecisionFailureKind.RETRYABLE
        return True

    async def mark_permanent_failure(
        self,
        *,
        tenant_id: int,
        outbox_id: int,
        claim_token: str,
        error_summary: str,
    ) -> bool:
        self.store.timeline.append(f"approval.fail:{outbox_id}")
        row = self.store.rows[outbox_id]
        if (
            int(row.tenant_id) != int(tenant_id)
            or row.status != ApprovalDecisionOutboxStatus.PROCESSING
            or row.claim_token != claim_token
        ):
            return False
        row.status = ApprovalDecisionOutboxStatus.FAILED
        row.retry_count += 1
        row.error_summary = error_summary
        row.next_retry_at = None
        row.failure_kind = ApprovalDecisionFailureKind.PERMANENT
        return True


class _Subscriber:
    scenario_code = SCENARIO_CODE
    subscriber_key = SCENARIO_CODE
    protocol_version = APPROVAL_DECISION_SUBSCRIBER_PROTOCOL_VERSION
    event_version = APPROVAL_DECISION_EVENT_VERSION
    completion_mode = DECISION_DELIVERY_COMPLETION_MODE

    def __init__(
        self,
        effects: list[Exception | Callable[[ApprovalDecisionEvent], None]] | None = None,
    ) -> None:
        self.effects = list(effects or [])
        self.received: list[ApprovalDecisionEvent] = []
        self.committed_event_ids: set[int] = set()
        self.timeline: list[str] | None = None

    async def accept(self, event: ApprovalDecisionEvent) -> None:
        self.received.append(event)
        if self.timeline is not None:
            self.timeline.append(f"business.accept:{event.event_id}")
        if self.effects:
            effect = self.effects.pop(0)
            if isinstance(effect, Exception):
                raise effect
            effect(event)
        self.committed_event_ids.add(event.event_id)
        if self.timeline is not None:
            self.timeline.append(f"business.commit:{event.event_id}")


def _outbox(
    *,
    row_id: int = 1,
    tenant_id: int = TENANT_ID,
    event_version: int = APPROVAL_DECISION_EVENT_VERSION,
    status: str = ApprovalDecisionOutboxStatus.PENDING,
    next_retry_at: datetime | None = None,
) -> ApprovalDecisionOutbox:
    return ApprovalDecisionOutbox(
        id=row_id,
        tenant_id=tenant_id,
        instance_id=1000 + row_id,
        scenario_code=SCENARIO_CODE,
        subscriber_key=SCENARIO_CODE,
        business_request_type="resource_user_invite_request",
        business_request_id=str(9000 + row_id),
        business_key=f"resource-user-invite:knowledge-space:{row_id}:user:9",
        request_fingerprint=f"request-fingerprint-{row_id}",
        decision="approved",
        decision_version=1,
        event_version=event_version,
        decided_at=NOW - timedelta(minutes=1),
        operator_user_id=9,
        status=status,
        next_retry_at=next_retry_at,
    )


def _service(
    *,
    store: _DecisionStore,
    subscriber: _Subscriber | None,
    clock: _Clock | None = None,
) -> tuple[ApprovalDecisionDeliveryService, _Clock]:
    registry = ApprovalRegistry()
    if subscriber is not None:
        subscriber.timeline = store.timeline
        registry.register_subscriber(subscriber)
    resolved_clock = clock or _Clock(NOW)
    service = ApprovalDecisionDeliveryService(
        registry=registry,
        session_factory=store.session_factory,
        repository_factory=store.repository_factory,
        now=resolved_clock.now,
        claim_token_factory=_TokenFactory(),
        lease_duration=LEASE_DURATION,
        retry_delay=RETRY_DELAY,
    )
    return service, resolved_clock


def _assert_terminal_and_event_identity_unchanged(store: _DecisionStore) -> None:
    assert tuple(sorted(store.rows)) == store.initial_event_ids
    assert store.approval_terminal_statuses == {int(row.instance_id): str(row.decision) for row in store.rows.values()}


@pytest.fixture(autouse=True)
def decision_delivery_tenant_context():
    token = current_tenant_id.set(TENANT_ID)
    try:
        yield
    finally:
        current_tenant_id.reset(token)


async def test_success_builds_versioned_event_and_acks_after_subscriber_returns():
    row = _outbox()
    store = _DecisionStore([row])
    subscriber = _Subscriber()
    service, _ = _service(store=store, subscriber=subscriber)

    event = await service.deliver_next(tenant_id=TENANT_ID)

    assert event == ApprovalDecisionEvent(
        event_id=1,
        event_version=1,
        decision_version=1,
        tenant_id=TENANT_ID,
        scenario_code=SCENARIO_CODE,
        approval_instance_id=1001,
        business_request_type="resource_user_invite_request",
        business_request_id="9001",
        business_key="resource-user-invite:knowledge-space:1:user:9",
        request_fingerprint="request-fingerprint-1",
        decision="approved",
        decided_at=NOW - timedelta(minutes=1),
        operator_user_id=9,
    )
    assert subscriber.received == [event]
    assert subscriber.committed_event_ids == {1}
    assert row.status == ApprovalDecisionOutboxStatus.DELIVERED
    assert store.timeline == [
        "approval.claim:1",
        "approval.commit",
        "business.accept:1",
        "business.commit:1",
        "approval.ack:1",
        "approval.commit",
    ]
    _assert_terminal_and_event_identity_unchanged(store)


@pytest.mark.parametrize(
    "message",
    [
        "business request not found",
        "business request tenant mismatch",
        "approval instance binding mismatch",
        "request fingerprint mismatch",
        "decision protocol mismatch",
        "out-of-order decision event",
    ],
)
async def test_business_binding_errors_are_permanent(message: str):
    row = _outbox()
    store = _DecisionStore([row])
    subscriber = _Subscriber([ApprovalDecisionPermanentError(message)])
    service, _ = _service(store=store, subscriber=subscriber)

    event = await service.deliver_next(tenant_id=TENANT_ID)

    assert event is not None and event.event_id == 1
    assert row.status == ApprovalDecisionOutboxStatus.FAILED
    assert row.failure_kind == ApprovalDecisionFailureKind.PERMANENT
    assert row.retry_count == 1
    assert row.error_summary == message
    _assert_terminal_and_event_identity_unchanged(store)


async def test_unknown_subscriber_is_a_permanent_delivery_failure():
    row = _outbox()
    store = _DecisionStore([row])
    service, _ = _service(store=store, subscriber=None)

    event = await service.deliver_next(tenant_id=TENANT_ID)

    assert event is not None and event.event_id == 1
    assert row.status == ApprovalDecisionOutboxStatus.FAILED
    assert row.failure_kind == ApprovalDecisionFailureKind.PERMANENT
    assert "subscriber" in str(row.error_summary)
    _assert_terminal_and_event_identity_unchanged(store)


@pytest.mark.parametrize("mismatch", ["event", "subscriber_protocol", "subscriber_event"])
async def test_delivery_protocol_mismatch_is_permanent(mismatch: str):
    row = _outbox(event_version=99 if mismatch == "event" else 1)
    store = _DecisionStore([row])
    subscriber = _Subscriber()
    if mismatch == "subscriber_protocol":
        subscriber.protocol_version = 99
    if mismatch == "subscriber_event":
        subscriber.event_version = 99
    service, _ = _service(store=store, subscriber=subscriber)

    event = await service.deliver_next(tenant_id=TENANT_ID)

    assert event is not None and event.event_id == 1
    assert subscriber.received == []
    assert row.status == ApprovalDecisionOutboxStatus.FAILED
    assert row.failure_kind == ApprovalDecisionFailureKind.PERMANENT
    assert "version" in str(row.error_summary)
    _assert_terminal_and_event_identity_unchanged(store)


@pytest.mark.parametrize(
    "error",
    [
        ApprovalDecisionRetryableError("database unavailable"),
        ApprovalDecisionRetryableError("broker unavailable"),
        RuntimeError("delivery process interrupted"),
    ],
)
async def test_temporary_subscriber_failures_are_scheduled_for_retry(error: Exception):
    row = _outbox()
    store = _DecisionStore([row])
    subscriber = _Subscriber([error])
    service, _ = _service(store=store, subscriber=subscriber)

    event = await service.deliver_next(tenant_id=TENANT_ID)

    assert event is not None and event.event_id == 1
    assert row.status == ApprovalDecisionOutboxStatus.PENDING
    assert row.failure_kind == ApprovalDecisionFailureKind.RETRYABLE
    assert row.retry_count == 1
    assert row.next_retry_at == NOW + RETRY_DELAY
    assert row.claim_token is None
    _assert_terminal_and_event_identity_unchanged(store)


async def test_ack_loss_reclaims_same_event_after_lease_without_reverting_approval():
    row = _outbox()
    store = _DecisionStore([row])
    store.ack_errors.append(OSError("database ack unavailable"))
    subscriber = _Subscriber()
    service, clock = _service(store=store, subscriber=subscriber)

    with pytest.raises(ApprovalDecisionRetryableError, match="ack"):
        await service.deliver_next(tenant_id=TENANT_ID)

    assert subscriber.received[0].event_id == 1
    assert subscriber.committed_event_ids == {1}
    assert row.status == ApprovalDecisionOutboxStatus.PROCESSING
    first_claim_token = row.claim_token
    assert row.claim_deadline == NOW + LEASE_DURATION
    _assert_terminal_and_event_identity_unchanged(store)

    clock.value = NOW + LEASE_DURATION + timedelta(seconds=1)
    event = await service.deliver_next(tenant_id=TENANT_ID)

    assert event is not None and event.event_id == 1
    assert [received.event_id for received in subscriber.received] == [1, 1]
    assert subscriber.committed_event_ids == {1}
    assert row.claim_token != first_claim_token
    assert row.status == ApprovalDecisionOutboxStatus.DELIVERED
    _assert_terminal_and_event_identity_unchanged(store)


async def test_delivered_duplicate_is_not_dispatched_again():
    row = _outbox()
    store = _DecisionStore([row])
    subscriber = _Subscriber()
    service, _ = _service(store=store, subscriber=subscriber)

    first = await service.deliver_next(tenant_id=TENANT_ID)
    duplicate = await service.deliver_next(tenant_id=TENANT_ID)

    assert first is not None and first.event_id == 1
    assert duplicate is None
    assert [event.event_id for event in subscriber.received] == [1]
    _assert_terminal_and_event_identity_unchanged(store)


async def test_delayed_retry_is_not_dispatched_before_due_time():
    row = _outbox(next_retry_at=NOW + RETRY_DELAY)
    store = _DecisionStore([row])
    subscriber = _Subscriber()
    service, clock = _service(store=store, subscriber=subscriber)

    assert await service.deliver_next(tenant_id=TENANT_ID) is None
    assert subscriber.received == []

    clock.value = NOW + RETRY_DELAY
    event = await service.deliver_next(tenant_id=TENANT_ID)

    assert event is not None and event.event_id == 1
    assert row.status == ApprovalDecisionOutboxStatus.DELIVERED
    _assert_terminal_and_event_identity_unchanged(store)


async def test_existing_events_are_delivered_by_stable_id_order_without_creating_events():
    later = _outbox(row_id=2)
    earlier = _outbox(row_id=1)
    store = _DecisionStore([later, earlier])
    subscriber = _Subscriber()
    service, _ = _service(store=store, subscriber=subscriber)

    first = await service.deliver_next(tenant_id=TENANT_ID)
    second = await service.deliver_next(tenant_id=TENANT_ID)

    assert first is not None and first.event_id == 1
    assert second is not None and second.event_id == 2
    assert [event.event_id for event in subscriber.received] == [1, 2]
    assert tuple(sorted(store.rows)) == (1, 2)
    _assert_terminal_and_event_identity_unchanged(store)
