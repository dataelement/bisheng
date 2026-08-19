from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_, or_, update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.approval.domain.models.approval_decision_outbox import (
    ApprovalDecisionFailureKind,
    ApprovalDecisionOutbox,
    ApprovalDecisionOutboxStatus,
)
from bisheng.core.context.tenant import get_current_tenant_id


class ApprovalDecisionOutboxRepository:
    """Caller-owned persistence primitives for reliable decision delivery."""

    MAX_RECOVERABLE_BATCH_SIZE = 500
    CLAIM_CANDIDATE_BATCH_SIZE = 32

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def _tenant_id(value: int) -> int:
        tenant_id = int(value)
        current_tenant_id = get_current_tenant_id()
        if current_tenant_id is None or tenant_id <= 0 or int(current_tenant_id) != tenant_id:
            raise ValueError("approval decision outbox requires the matching tenant context")
        return tenant_id

    @staticmethod
    def _claim_token(value: str) -> str:
        claim_token = str(value).strip()
        if not claim_token:
            raise ValueError("claim_token must not be empty")
        return claim_token

    @staticmethod
    def _recoverable_condition(*, now: datetime):
        return or_(
            and_(
                ApprovalDecisionOutbox.status == ApprovalDecisionOutboxStatus.PENDING,
                or_(
                    ApprovalDecisionOutbox.next_retry_at.is_(None),
                    ApprovalDecisionOutbox.next_retry_at <= now,
                ),
            ),
            and_(
                ApprovalDecisionOutbox.status == ApprovalDecisionOutboxStatus.PROCESSING,
                ApprovalDecisionOutbox.claim_deadline <= now,
            ),
        )

    async def list_recoverable(
        self,
        *,
        tenant_id: int,
        now: datetime,
        after_outbox_id: int = 0,
        limit: int = 100,
    ) -> list[ApprovalDecisionOutbox]:
        """List due pending events and expired leases using a bounded keyset."""

        resolved_tenant_id = self._tenant_id(tenant_id)
        bounded_limit = max(1, min(int(limit), self.MAX_RECOVERABLE_BATCH_SIZE))
        statement = (
            select(ApprovalDecisionOutbox)
            .where(
                ApprovalDecisionOutbox.tenant_id == resolved_tenant_id,
                ApprovalDecisionOutbox.id > int(after_outbox_id),
                self._recoverable_condition(now=now),
            )
            .order_by(ApprovalDecisionOutbox.id.asc())
            .limit(bounded_limit)
        )
        return list((await self.session.exec(statement)).all())

    async def claim_next(
        self,
        *,
        tenant_id: int,
        claim_token: str,
        now: datetime,
        claim_deadline: datetime,
    ) -> ApprovalDecisionOutbox | None:
        """Atomically claim one recoverable event without committing the session."""

        resolved_tenant_id = self._tenant_id(tenant_id)
        resolved_claim_token = self._claim_token(claim_token)
        if claim_deadline <= now:
            raise ValueError("claim_deadline must be later than now")

        candidate_statement = (
            select(ApprovalDecisionOutbox.id)
            .where(
                ApprovalDecisionOutbox.tenant_id == resolved_tenant_id,
                self._recoverable_condition(now=now),
            )
            .order_by(ApprovalDecisionOutbox.id.asc())
            .limit(self.CLAIM_CANDIDATE_BATCH_SIZE)
        )
        dialect_name = self.session.get_bind().dialect.name
        if dialect_name == "mysql":
            candidate_statement = candidate_statement.with_for_update(skip_locked=True)
        elif dialect_name != "sqlite":
            # DaMeng supports portable FOR UPDATE, while SKIP LOCKED support
            # depends on the deployed server/dialect version. The conditional
            # UPDATE below remains the final ownership guard on every dialect.
            candidate_statement = candidate_statement.with_for_update()
        candidate_ids = list((await self.session.exec(candidate_statement)).all())
        for candidate_id in candidate_ids:
            claim_statement = (
                update(ApprovalDecisionOutbox)
                .where(
                    ApprovalDecisionOutbox.id == int(candidate_id),
                    ApprovalDecisionOutbox.tenant_id == resolved_tenant_id,
                    self._recoverable_condition(now=now),
                )
                .values(
                    status=ApprovalDecisionOutboxStatus.PROCESSING,
                    claim_token=resolved_claim_token,
                    claimed_at=now,
                    claim_deadline=claim_deadline,
                    next_retry_at=None,
                )
            )
            result = await self.session.exec(claim_statement)
            if not result.rowcount:
                continue
            await self.session.flush()
            return await self._get_for_owner(
                tenant_id=resolved_tenant_id,
                outbox_id=int(candidate_id),
                claim_token=resolved_claim_token,
            )
        return None

    async def mark_delivered(
        self,
        *,
        tenant_id: int,
        outbox_id: int,
        claim_token: str,
    ) -> bool:
        """Acknowledge delivery for the current token; repeat ack is successful."""

        resolved_tenant_id = self._tenant_id(tenant_id)
        resolved_claim_token = self._claim_token(claim_token)
        statement = (
            update(ApprovalDecisionOutbox)
            .where(
                ApprovalDecisionOutbox.id == int(outbox_id),
                ApprovalDecisionOutbox.tenant_id == resolved_tenant_id,
                ApprovalDecisionOutbox.status == ApprovalDecisionOutboxStatus.PROCESSING,
                ApprovalDecisionOutbox.claim_token == resolved_claim_token,
            )
            .values(
                status=ApprovalDecisionOutboxStatus.DELIVERED,
                error_summary=None,
                next_retry_at=None,
                failure_kind=None,
            )
        )
        result = await self.session.exec(statement)
        if result.rowcount:
            await self.session.flush()
            return True
        return await self._has_status_for_owner(
            tenant_id=resolved_tenant_id,
            outbox_id=int(outbox_id),
            claim_token=resolved_claim_token,
            status=ApprovalDecisionOutboxStatus.DELIVERED,
        )

    async def mark_retryable_failure(
        self,
        *,
        tenant_id: int,
        outbox_id: int,
        claim_token: str,
        error_summary: str,
        next_retry_at: datetime,
    ) -> bool:
        """Release the claim and schedule the same event for a later retry."""

        resolved_tenant_id = self._tenant_id(tenant_id)
        resolved_claim_token = self._claim_token(claim_token)
        statement = (
            update(ApprovalDecisionOutbox)
            .where(
                ApprovalDecisionOutbox.id == int(outbox_id),
                ApprovalDecisionOutbox.tenant_id == resolved_tenant_id,
                ApprovalDecisionOutbox.status == ApprovalDecisionOutboxStatus.PROCESSING,
                ApprovalDecisionOutbox.claim_token == resolved_claim_token,
            )
            .values(
                status=ApprovalDecisionOutboxStatus.PENDING,
                claim_token=None,
                claimed_at=None,
                claim_deadline=None,
                retry_count=ApprovalDecisionOutbox.retry_count + 1,
                error_summary=str(error_summary),
                next_retry_at=next_retry_at,
                failure_kind=ApprovalDecisionFailureKind.RETRYABLE,
            )
        )
        result = await self.session.exec(statement)
        await self.session.flush()
        return bool(result.rowcount)

    async def mark_permanent_failure(
        self,
        *,
        tenant_id: int,
        outbox_id: int,
        claim_token: str,
        error_summary: str,
    ) -> bool:
        """Stop automatic delivery after a permanent protocol or binding error."""

        resolved_tenant_id = self._tenant_id(tenant_id)
        resolved_claim_token = self._claim_token(claim_token)
        statement = (
            update(ApprovalDecisionOutbox)
            .where(
                ApprovalDecisionOutbox.id == int(outbox_id),
                ApprovalDecisionOutbox.tenant_id == resolved_tenant_id,
                ApprovalDecisionOutbox.status == ApprovalDecisionOutboxStatus.PROCESSING,
                ApprovalDecisionOutbox.claim_token == resolved_claim_token,
            )
            .values(
                status=ApprovalDecisionOutboxStatus.FAILED,
                retry_count=ApprovalDecisionOutbox.retry_count + 1,
                error_summary=str(error_summary),
                next_retry_at=None,
                failure_kind=ApprovalDecisionFailureKind.PERMANENT,
            )
        )
        result = await self.session.exec(statement)
        await self.session.flush()
        return bool(result.rowcount)

    async def _get_for_owner(
        self,
        *,
        tenant_id: int,
        outbox_id: int,
        claim_token: str,
    ) -> ApprovalDecisionOutbox | None:
        statement = (
            select(ApprovalDecisionOutbox)
            .where(
                ApprovalDecisionOutbox.id == outbox_id,
                ApprovalDecisionOutbox.tenant_id == tenant_id,
                ApprovalDecisionOutbox.claim_token == claim_token,
            )
            .execution_options(populate_existing=True)
        )
        return (await self.session.exec(statement)).first()

    async def _has_status_for_owner(
        self,
        *,
        tenant_id: int,
        outbox_id: int,
        claim_token: str,
        status: str,
    ) -> bool:
        statement = select(ApprovalDecisionOutbox.id).where(
            ApprovalDecisionOutbox.id == outbox_id,
            ApprovalDecisionOutbox.tenant_id == tenant_id,
            ApprovalDecisionOutbox.claim_token == claim_token,
            ApprovalDecisionOutbox.status == status,
        )
        return (await self.session.exec(statement)).first() is not None
