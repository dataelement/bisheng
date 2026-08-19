from __future__ import annotations

from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.approval.domain.models.approval_decision_outbox import (
    ApprovalDecisionFailureKind,
    ApprovalDecisionOutbox,
    ApprovalDecisionOutboxStatus,
)
from bisheng.approval.domain.repositories.approval_decision_outbox_repository import (
    ApprovalDecisionOutboxRepository,
)
from bisheng.core.context.tenant import current_tenant_id

TENANT_ID = 42
NOW = datetime(2026, 8, 13, 9, 0, 0)


@pytest_asyncio.fixture(autouse=True)
async def decision_outbox_tenant_context():
    token = current_tenant_id.set(TENANT_ID)
    try:
        yield
    finally:
        current_tenant_id.reset(token)


@pytest_asyncio.fixture
async def decision_outbox_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda conn: SQLModel.metadata.create_all(
                conn,
                tables=[ApprovalDecisionOutbox.__table__],
            )
        )
    yield engine
    await engine.dispose()


def _event(
    *,
    row_id: int,
    tenant_id: int = TENANT_ID,
    status: str = ApprovalDecisionOutboxStatus.PENDING,
    claim_token: str | None = None,
    claimed_at: datetime | None = None,
    claim_deadline: datetime | None = None,
    next_retry_at: datetime | None = None,
) -> ApprovalDecisionOutbox:
    return ApprovalDecisionOutbox(
        id=row_id,
        tenant_id=tenant_id,
        instance_id=row_id + tenant_id * 1000,
        scenario_code="resource_user_invite_confirmation",
        subscriber_key="resource_user_invite_confirmation",
        business_request_type="resource_user_invite_request",
        business_request_id=str(row_id + tenant_id * 10000),
        business_key=f"tenant:{tenant_id}:invite:{row_id}",
        request_fingerprint=f"fingerprint-{tenant_id}-{row_id}",
        decision="approved",
        decided_at=NOW - timedelta(minutes=1),
        operator_user_id=9,
        status=status,
        claim_token=claim_token,
        claimed_at=claimed_at,
        claim_deadline=claim_deadline,
        next_retry_at=next_retry_at,
    )


async def _seed(engine, *events: ApprovalDecisionOutbox) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add_all(events)
        await session.commit()


async def _load(engine, outbox_id: int) -> ApprovalDecisionOutbox:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        row = await session.get(ApprovalDecisionOutbox, outbox_id)
        assert row is not None
        return row


async def test_pending_event_can_be_claimed(decision_outbox_engine):
    await _seed(decision_outbox_engine, _event(row_id=1))
    deadline = NOW + timedelta(minutes=5)

    async with AsyncSession(decision_outbox_engine, expire_on_commit=False) as session:
        claimed = await ApprovalDecisionOutboxRepository(session).claim_next(
            tenant_id=TENANT_ID,
            claim_token="claim-1",
            now=NOW,
            claim_deadline=deadline,
        )
        await session.commit()

    assert claimed is not None
    assert claimed.id == 1
    assert claimed.status == ApprovalDecisionOutboxStatus.PROCESSING
    assert claimed.claim_token == "claim-1"
    assert claimed.claimed_at == NOW
    assert claimed.claim_deadline == deadline


async def test_unexpired_processing_event_is_not_reclaimed(decision_outbox_engine):
    await _seed(
        decision_outbox_engine,
        _event(
            row_id=1,
            status=ApprovalDecisionOutboxStatus.PROCESSING,
            claim_token="active-claim",
            claimed_at=NOW - timedelta(minutes=1),
            claim_deadline=NOW + timedelta(minutes=4),
        ),
    )

    async with AsyncSession(decision_outbox_engine, expire_on_commit=False) as session:
        claimed = await ApprovalDecisionOutboxRepository(session).claim_next(
            tenant_id=TENANT_ID,
            claim_token="competing-claim",
            now=NOW,
            claim_deadline=NOW + timedelta(minutes=5),
        )

    assert claimed is None
    saved = await _load(decision_outbox_engine, 1)
    assert saved.claim_token == "active-claim"
    assert saved.claim_deadline == NOW + timedelta(minutes=4)


async def test_expired_processing_event_is_reclaimed_with_new_token(decision_outbox_engine):
    await _seed(
        decision_outbox_engine,
        _event(
            row_id=1,
            status=ApprovalDecisionOutboxStatus.PROCESSING,
            claim_token="expired-claim",
            claimed_at=NOW - timedelta(minutes=10),
            claim_deadline=NOW - timedelta(seconds=1),
        ),
    )
    new_deadline = NOW + timedelta(minutes=5)

    async with AsyncSession(decision_outbox_engine, expire_on_commit=False) as session:
        claimed = await ApprovalDecisionOutboxRepository(session).claim_next(
            tenant_id=TENANT_ID,
            claim_token="replacement-claim",
            now=NOW,
            claim_deadline=new_deadline,
        )
        await session.commit()

    assert claimed is not None
    assert claimed.id == 1
    assert claimed.claim_token == "replacement-claim"
    assert claimed.claimed_at == NOW
    assert claimed.claim_deadline == new_deadline


async def test_wrong_claim_token_cannot_ack_delivery(decision_outbox_engine):
    await _seed(
        decision_outbox_engine,
        _event(
            row_id=1,
            status=ApprovalDecisionOutboxStatus.PROCESSING,
            claim_token="owner-claim",
            claimed_at=NOW,
            claim_deadline=NOW + timedelta(minutes=5),
        ),
    )

    async with AsyncSession(decision_outbox_engine, expire_on_commit=False) as session:
        acknowledged = await ApprovalDecisionOutboxRepository(session).mark_delivered(
            tenant_id=TENANT_ID,
            outbox_id=1,
            claim_token="wrong-claim",
        )
        await session.commit()

    assert acknowledged is False
    saved = await _load(decision_outbox_engine, 1)
    assert saved.status == ApprovalDecisionOutboxStatus.PROCESSING
    assert saved.claim_token == "owner-claim"


async def test_retryable_failure_returns_event_to_pending(decision_outbox_engine):
    await _seed(
        decision_outbox_engine,
        _event(
            row_id=1,
            status=ApprovalDecisionOutboxStatus.PROCESSING,
            claim_token="owner-claim",
            claimed_at=NOW,
            claim_deadline=NOW + timedelta(minutes=5),
        ),
    )
    next_retry_at = NOW + timedelta(minutes=2)

    async with AsyncSession(decision_outbox_engine, expire_on_commit=False) as session:
        released = await ApprovalDecisionOutboxRepository(session).mark_retryable_failure(
            tenant_id=TENANT_ID,
            outbox_id=1,
            claim_token="owner-claim",
            error_summary="temporary database outage",
            next_retry_at=next_retry_at,
        )
        await session.commit()

    assert released is True
    saved = await _load(decision_outbox_engine, 1)
    assert saved.status == ApprovalDecisionOutboxStatus.PENDING
    assert saved.failure_kind == ApprovalDecisionFailureKind.RETRYABLE
    assert saved.retry_count == 1
    assert saved.error_summary == "temporary database outage"
    assert saved.next_retry_at == next_retry_at
    assert saved.claim_token is None
    assert saved.claimed_at is None
    assert saved.claim_deadline is None


async def test_permanent_failure_moves_event_to_failed(decision_outbox_engine):
    await _seed(
        decision_outbox_engine,
        _event(
            row_id=1,
            status=ApprovalDecisionOutboxStatus.PROCESSING,
            claim_token="owner-claim",
            claimed_at=NOW,
            claim_deadline=NOW + timedelta(minutes=5),
        ),
    )

    async with AsyncSession(decision_outbox_engine, expire_on_commit=False) as session:
        failed = await ApprovalDecisionOutboxRepository(session).mark_permanent_failure(
            tenant_id=TENANT_ID,
            outbox_id=1,
            claim_token="owner-claim",
            error_summary="request fingerprint mismatch",
        )
        await session.commit()

    assert failed is True
    saved = await _load(decision_outbox_engine, 1)
    assert saved.status == ApprovalDecisionOutboxStatus.FAILED
    assert saved.failure_kind == ApprovalDecisionFailureKind.PERMANENT
    assert saved.retry_count == 1
    assert saved.error_summary == "request fingerprint mismatch"
    assert saved.next_retry_at is None


async def test_delivered_ack_is_idempotent_for_owning_token(decision_outbox_engine):
    await _seed(
        decision_outbox_engine,
        _event(
            row_id=1,
            status=ApprovalDecisionOutboxStatus.PROCESSING,
            claim_token="owner-claim",
            claimed_at=NOW,
            claim_deadline=NOW + timedelta(minutes=5),
        ),
    )

    async with AsyncSession(decision_outbox_engine, expire_on_commit=False) as session:
        repository = ApprovalDecisionOutboxRepository(session)
        first = await repository.mark_delivered(
            tenant_id=TENANT_ID,
            outbox_id=1,
            claim_token="owner-claim",
        )
        second = await repository.mark_delivered(
            tenant_id=TENANT_ID,
            outbox_id=1,
            claim_token="owner-claim",
        )
        await session.commit()

    assert first is True
    assert second is True
    saved = await _load(decision_outbox_engine, 1)
    assert saved.status == ApprovalDecisionOutboxStatus.DELIVERED
    assert saved.claim_token == "owner-claim"
    assert saved.retry_count == 0
    assert saved.error_summary is None


async def test_claim_is_strictly_tenant_isolated(decision_outbox_engine):
    await _seed(
        decision_outbox_engine,
        _event(row_id=1, tenant_id=43),
        _event(row_id=2, tenant_id=TENANT_ID),
    )

    async with AsyncSession(decision_outbox_engine, expire_on_commit=False) as session:
        claimed = await ApprovalDecisionOutboxRepository(session).claim_next(
            tenant_id=TENANT_ID,
            claim_token="tenant-42-claim",
            now=NOW,
            claim_deadline=NOW + timedelta(minutes=5),
        )
        await session.commit()

    assert claimed is not None
    assert claimed.id == 2
    assert claimed.tenant_id == TENANT_ID
    other_tenant = await _load(decision_outbox_engine, 1)
    assert other_tenant.status == ApprovalDecisionOutboxStatus.PENDING
    assert other_tenant.claim_token is None


@pytest.mark.parametrize("context_tenant_id", [None, 43])
async def test_repository_fails_closed_without_matching_tenant_context(
    decision_outbox_engine,
    context_tenant_id,
):
    token = current_tenant_id.set(context_tenant_id)
    try:
        async with AsyncSession(decision_outbox_engine, expire_on_commit=False) as session:
            with pytest.raises(ValueError, match="matching tenant context"):
                await ApprovalDecisionOutboxRepository(session).list_recoverable(
                    tenant_id=TENANT_ID,
                    now=NOW,
                )
    finally:
        current_tenant_id.reset(token)
