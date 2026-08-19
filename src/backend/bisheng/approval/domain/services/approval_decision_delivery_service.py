from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from loguru import logger
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.approval.domain.models.approval_decision_outbox import ApprovalDecisionOutbox
from bisheng.approval.domain.ports.decision_subscriber import (
    APPROVAL_DECISION_EVENT_VERSION,
    APPROVAL_DECISION_SUBSCRIBER_PROTOCOL_VERSION,
    ApprovalDecisionEvent,
    ApprovalDecisionPermanentError,
    ApprovalDecisionRetryableError,
    ApprovalDecisionSubscriber,
)
from bisheng.approval.domain.ports.scenario_policy import DECISION_DELIVERY_COMPLETION_MODE
from bisheng.approval.domain.repositories.approval_decision_outbox_repository import (
    ApprovalDecisionOutboxRepository,
)
from bisheng.approval.domain.services.approval_registry import ApprovalRegistry
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.database import get_async_db_session

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
RepositoryFactory = Callable[[AsyncSession], ApprovalDecisionOutboxRepository]


class ApprovalDecisionDeliveryService:
    """Deliver terminal approval facts without owning business execution."""

    def __init__(
        self,
        *,
        registry: ApprovalRegistry,
        session_factory: SessionFactory = get_async_db_session,
        repository_factory: RepositoryFactory = ApprovalDecisionOutboxRepository,
        now: Callable[[], datetime] = lambda: datetime.now(UTC).replace(tzinfo=None),
        claim_token_factory: Callable[[], str] = lambda: str(uuid4()),
        lease_duration: timedelta = timedelta(minutes=5),
        retry_delay: timedelta = timedelta(seconds=30),
    ) -> None:
        if lease_duration <= timedelta(0):
            raise ValueError("approval decision lease_duration must be positive")
        if retry_delay < timedelta(0):
            raise ValueError("approval decision retry_delay must not be negative")
        self.registry = registry
        self.session_factory = session_factory
        self.repository_factory = repository_factory
        self.now = now
        self.claim_token_factory = claim_token_factory
        self.lease_duration = lease_duration
        self.retry_delay = retry_delay

    @staticmethod
    def _require_tenant(tenant_id: int) -> int:
        normalized_tenant_id = int(tenant_id)
        current_tenant_id = get_current_tenant_id()
        if normalized_tenant_id <= 0 or current_tenant_id is None or int(current_tenant_id) != normalized_tenant_id:
            raise ValueError("approval decision delivery requires the matching tenant context")
        return normalized_tenant_id

    async def deliver_next(self, *, tenant_id: int) -> ApprovalDecisionEvent | None:
        """Claim and deliver one due event for the active tenant."""

        resolved_tenant_id = self._require_tenant(tenant_id)
        attempt_now = self.now()
        claim_token = str(self.claim_token_factory()).strip()
        if not claim_token:
            raise ValueError("approval decision claim token must not be empty")

        try:
            async with self.session_factory() as session:
                claimed = await self.repository_factory(session).claim_next(
                    tenant_id=resolved_tenant_id,
                    claim_token=claim_token,
                    now=attempt_now,
                    claim_deadline=attempt_now + self.lease_duration,
                )
                if claimed is None:
                    return None
                await session.commit()
        except Exception as error:
            raise ApprovalDecisionRetryableError("approval decision claim failed") from error

        event = self._build_event(claimed)
        delivery_logger = logger.bind(
            event_id=event.event_id,
            tenant_id=event.tenant_id,
            approval_instance_id=event.approval_instance_id,
            business_request_id=event.business_request_id,
        )
        delivery_logger.info("approval decision delivery claimed")

        try:
            subscriber = self._resolve_subscriber(claimed)
        except ApprovalDecisionPermanentError as error:
            await self._mark_permanent_failure(
                event=event,
                claim_token=claim_token,
                error=error,
            )
            delivery_logger.warning("approval decision delivery rejected permanently: {}", str(error))
            return event

        try:
            await subscriber.accept(event)
        except ApprovalDecisionPermanentError as error:
            await self._mark_permanent_failure(
                event=event,
                claim_token=claim_token,
                error=error,
            )
            delivery_logger.warning("approval decision subscriber rejected event permanently: {}", str(error))
            return event
        except ApprovalDecisionRetryableError as error:
            await self._mark_retryable_failure(
                event=event,
                claim_token=claim_token,
                error=error,
            )
            delivery_logger.warning("approval decision subscriber temporarily unavailable: {}", str(error))
            return event
        except Exception as error:
            retryable_error = ApprovalDecisionRetryableError(str(error) or type(error).__name__)
            await self._mark_retryable_failure(
                event=event,
                claim_token=claim_token,
                error=retryable_error,
            )
            delivery_logger.exception("approval decision subscriber raised an unclassified error")
            return event

        await self._ack_delivered(event=event, claim_token=claim_token)
        delivery_logger.info("approval decision delivery acknowledged")
        return event

    @staticmethod
    def _build_event(row: ApprovalDecisionOutbox) -> ApprovalDecisionEvent:
        return ApprovalDecisionEvent(
            event_id=int(row.id),
            event_version=int(row.event_version),
            decision_version=int(row.decision_version),
            tenant_id=int(row.tenant_id),
            scenario_code=str(row.scenario_code),
            approval_instance_id=int(row.instance_id),
            business_request_type=str(row.business_request_type),
            business_request_id=str(row.business_request_id),
            business_key=str(row.business_key),
            request_fingerprint=str(row.request_fingerprint),
            decision=row.decision,
            decided_at=row.decided_at,
            operator_user_id=row.operator_user_id,
        )

    def _resolve_subscriber(self, row: ApprovalDecisionOutbox) -> ApprovalDecisionSubscriber:
        if int(row.event_version) != APPROVAL_DECISION_EVENT_VERSION:
            raise ApprovalDecisionPermanentError(f"approval decision event version mismatch: {row.event_version}")
        if int(row.decision_version) != 1:
            raise ApprovalDecisionPermanentError(f"approval decision version mismatch: {row.decision_version}")
        try:
            subscriber = self.registry.get_subscriber(str(row.scenario_code))
        except KeyError as error:
            raise ApprovalDecisionPermanentError(
                f"approval decision subscriber is not registered: {row.subscriber_key}"
            ) from error
        if subscriber.scenario_code != row.scenario_code or subscriber.subscriber_key != row.subscriber_key:
            raise ApprovalDecisionPermanentError("approval decision subscriber binding mismatch")
        if subscriber.protocol_version != APPROVAL_DECISION_SUBSCRIBER_PROTOCOL_VERSION:
            raise ApprovalDecisionPermanentError(
                f"approval decision subscriber protocol version mismatch: {subscriber.protocol_version}"
            )
        if subscriber.event_version != int(row.event_version):
            raise ApprovalDecisionPermanentError(
                f"approval decision subscriber event version mismatch: {subscriber.event_version}"
            )
        if subscriber.completion_mode != DECISION_DELIVERY_COMPLETION_MODE:
            raise ApprovalDecisionPermanentError("approval decision subscriber completion mode mismatch")
        return subscriber

    async def _ack_delivered(self, *, event: ApprovalDecisionEvent, claim_token: str) -> None:
        try:
            async with self.session_factory() as session:
                acknowledged = await self.repository_factory(session).mark_delivered(
                    tenant_id=event.tenant_id,
                    outbox_id=event.event_id,
                    claim_token=claim_token,
                )
                if not acknowledged:
                    raise ApprovalDecisionRetryableError("approval decision ack lost claim ownership")
                await session.commit()
        except ApprovalDecisionRetryableError:
            raise
        except Exception as error:
            raise ApprovalDecisionRetryableError("approval decision ack failed") from error

    async def _mark_retryable_failure(
        self,
        *,
        event: ApprovalDecisionEvent,
        claim_token: str,
        error: Exception,
    ) -> None:
        try:
            async with self.session_factory() as session:
                marked = await self.repository_factory(session).mark_retryable_failure(
                    tenant_id=event.tenant_id,
                    outbox_id=event.event_id,
                    claim_token=claim_token,
                    error_summary=self._error_summary(error),
                    next_retry_at=self.now() + self.retry_delay,
                )
                if not marked:
                    raise ApprovalDecisionRetryableError("approval decision retry lost claim ownership")
                await session.commit()
        except ApprovalDecisionRetryableError:
            raise
        except Exception as persistence_error:
            raise ApprovalDecisionRetryableError(
                "approval decision retry state could not be persisted"
            ) from persistence_error

    async def _mark_permanent_failure(
        self,
        *,
        event: ApprovalDecisionEvent,
        claim_token: str,
        error: Exception,
    ) -> None:
        try:
            async with self.session_factory() as session:
                marked = await self.repository_factory(session).mark_permanent_failure(
                    tenant_id=event.tenant_id,
                    outbox_id=event.event_id,
                    claim_token=claim_token,
                    error_summary=self._error_summary(error),
                )
                if not marked:
                    raise ApprovalDecisionRetryableError("approval decision permanent failure lost claim ownership")
                await session.commit()
        except ApprovalDecisionRetryableError:
            raise
        except Exception as persistence_error:
            raise ApprovalDecisionRetryableError(
                "approval decision permanent failure could not be persisted"
            ) from persistence_error

    @staticmethod
    def _error_summary(error: Exception) -> str:
        summary = str(error).strip() or type(error).__name__
        return summary[:2000]


__all__ = ["ApprovalDecisionDeliveryService"]
