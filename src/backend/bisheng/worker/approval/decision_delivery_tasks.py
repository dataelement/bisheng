from __future__ import annotations

from datetime import UTC, datetime

from loguru import logger

from bisheng.approval.domain.ports.decision_subscriber import ApprovalDecisionRetryableError
from bisheng.approval.domain.repositories.approval_decision_outbox_repository import (
    ApprovalDecisionOutboxRepository,
)
from bisheng.approval.domain.services.approval_decision_delivery_service import (
    ApprovalDecisionDeliveryService,
)
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery

DECISION_DELIVERY_SCAN_BATCH_SIZE = 100
_DELIVERY_RETRY_OPTIONS = {
    "autoretry_for": (ApprovalDecisionRetryableError,),
    "retry_backoff": True,
    "retry_jitter": True,
    "retry_kwargs": {"max_retries": 8},
}


@bisheng_celery.task(
    bind=True,
    acks_late=True,
    time_limit=300,
    soft_time_limit=270,
    name="bisheng.worker.approval.decision_delivery_tasks.deliver_approval_decision",
    **_DELIVERY_RETRY_OPTIONS,
)
def deliver_approval_decision(self) -> dict:
    """Attempt one tenant-scoped decision event; the outbox remains authoritative."""

    return _run_in_task_tenant(
        request=self.request,
        coroutine_factory=lambda tenant_id: _deliver_one_async(tenant_id=tenant_id),
    )


@bisheng_celery.task(
    bind=True,
    acks_late=True,
    time_limit=300,
    soft_time_limit=270,
    name="bisheng.worker.approval.decision_delivery_tasks.coordinate_approval_decision_delivery",
)
def coordinate_approval_decision_delivery(
    self,
    *,
    after_event_id: int = 0,
) -> dict:
    """Dispatch one bounded recoverable page without claiming business completion."""

    return _run_in_task_tenant(
        request=self.request,
        coroutine_factory=lambda tenant_id: _coordinate_recoverable_async(
            tenant_id=tenant_id,
            after_event_id=int(after_event_id),
            limit=DECISION_DELIVERY_SCAN_BATCH_SIZE,
        ),
    )


def _run_in_task_tenant(*, request, coroutine_factory):
    tenant_id = _require_tenant_id_header(request)
    tenant_token = set_current_tenant_id(tenant_id)
    try:
        return run_async_task(lambda: coroutine_factory(tenant_id))
    finally:
        current_tenant_id.reset(tenant_token)


def _require_tenant_id_header(request) -> int:
    headers = getattr(request, "headers", None) or {}
    raw_tenant_id = headers.get("tenant_id")
    if raw_tenant_id is None or isinstance(raw_tenant_id, bool):
        raise ValueError("approval decision worker requires a tenant_id header")
    try:
        tenant_id = int(raw_tenant_id)
    except (TypeError, ValueError) as error:
        raise ValueError("approval decision worker tenant_id header must be a positive integer") from error
    if tenant_id <= 0:
        raise ValueError("approval decision worker tenant_id header must be a positive integer")
    return tenant_id


def _build_delivery_service() -> ApprovalDecisionDeliveryService:
    # The composition root is introduced by T019. Keeping this import lazy
    # lets task registration remain I/O-free and avoids duplicating bootstrap.
    from bisheng.bootstrap.approval_scenarios import bootstrap_approval_scenarios

    return ApprovalDecisionDeliveryService(registry=bootstrap_approval_scenarios())


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def _deliver_one_async(*, tenant_id: int) -> dict:
    event = await _build_delivery_service().deliver_next(tenant_id=int(tenant_id))
    if event is None:
        return {"claimed": False, "event_id": None}
    return {"claimed": True, "event_id": int(event.event_id)}


async def _coordinate_recoverable_async(
    *,
    tenant_id: int,
    after_event_id: int,
    limit: int,
) -> dict:
    tenant_id = int(tenant_id)
    bounded_limit = max(1, min(int(limit), DECISION_DELIVERY_SCAN_BATCH_SIZE))
    async with get_async_db_session() as session:
        rows = await ApprovalDecisionOutboxRepository(session).list_recoverable(
            tenant_id=tenant_id,
            now=_utc_now(),
            after_outbox_id=int(after_event_id),
            limit=bounded_limit + 1,
        )

    has_more = len(rows) > bounded_limit
    page = rows[:bounded_limit]
    broker_task_ids: list[str] = []
    dispatched = 0
    dispatch_failed = 0
    for row in page:
        try:
            dispatched_task = deliver_approval_decision.apply_async(headers={"tenant_id": tenant_id})
        except Exception:
            dispatch_failed += 1
            logger.bind(
                event_id=int(row.id),
                tenant_id=tenant_id,
                approval_instance_id=getattr(row, "instance_id", None),
                business_request_id=getattr(row, "business_request_id", None),
            ).exception("failed to dispatch approval decision delivery task")
            continue
        dispatched += 1
        broker_task_id = getattr(dispatched_task, "id", None)
        if broker_task_id is not None:
            broker_task_ids.append(str(broker_task_id))

    next_after_event_id = int(page[-1].id) if page else int(after_event_id)
    continuation_task_id: str | None = None
    if has_more:
        try:
            continuation = coordinate_approval_decision_delivery.apply_async(
                kwargs={"after_event_id": next_after_event_id},
                headers={"tenant_id": tenant_id},
            )
            raw_continuation_id = getattr(continuation, "id", None)
            if raw_continuation_id is not None:
                continuation_task_id = str(raw_continuation_id)
        except Exception:
            logger.bind(
                event_id=next_after_event_id,
                tenant_id=tenant_id,
                approval_instance_id=None,
                business_request_id=None,
            ).exception("failed to dispatch approval decision delivery continuation")

    return {
        "scanned": len(page),
        "dispatched": dispatched,
        "dispatch_failed": dispatch_failed,
        "has_more": has_more,
        "next_after_event_id": next_after_event_id,
        "broker_task_ids": broker_task_ids,
        "continuation_task_id": continuation_task_id,
    }


__all__ = [
    "coordinate_approval_decision_delivery",
    "deliver_approval_decision",
]
