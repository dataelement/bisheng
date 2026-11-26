"""F026: a wakeup authorizes at most one leased step; it is not a receipt."""

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from loguru import logger

from bisheng.core.context.tenant import bypass_tenant_filter, tenant_execution_scope
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderOperation
from bisheng.knowledge.domain.repositories.provider_operation_repository import ProviderOperationRepository
from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery

# One provisioning step may run a full round of remote model probes, and the
# send step always does (creation never trusts a cached probe), so a fixed budget
# cannot work: 120s cut real sends off mid-write and the operation then retried
# forever. The step and lease budgets are therefore derived from the operator's
# probe budget.
STEP_OVERHEAD_SECONDS = 120
LEASE_MARGIN_SECONDS = 60
INSTANCE_CONCURRENCY = 2
ATTEMPT_BUDGET = 8
# The states a wakeup can advance. A step that lands outside them is terminal or
# parked for review and must not be woken again.
_WAKEABLE = frozenset({"pending", "sending", "waiting_remote", "reconciling", "applying"})


def should_chain_wakeup(*, state, delay) -> bool:
    """A phase transition is due now; a retry waits for its own backoff."""
    return delay == 0 and state in _WAKEABLE


def wake_provider_operation(*, tenant_id, operation_id, expected_revision, queue="knowledge_celery") -> bool:
    """Ask a worker to advance this operation now.

    The periodic sweep stays the safety net, so a broker that is down must not
    turn a committed operation into a failed request. ``expected_revision`` is
    bound into the message: a wakeup for a revision the row has already left is
    discarded by ``_execute`` instead of advancing someone else's claim.
    """
    try:
        advance_provider_operation.apply_async(
            kwargs={"operation_id": operation_id, "expected_revision": expected_revision},
            headers={"tenant_id": tenant_id},
            queue=queue,
            retry=False,
        )
        return True
    except Exception:
        logger.warning("provider operation wakeup unavailable operation={}", operation_id)
        return False


def step_timeout_seconds() -> float:
    """Wall-clock budget for one leased step (never less than before, so nothing regresses)."""
    from bisheng.knowledge.application.provider_provision_runtime import probe_budget_seconds

    return max(120.0, probe_budget_seconds() + STEP_OVERHEAD_SECONDS)


def lease_seconds() -> int:
    """Lease must outlive the step it covers, or a peer reclaims work that is still running."""
    return int(step_timeout_seconds() + LEASE_MARGIN_SECONDS)


@dataclass(frozen=True)
class StepResult:
    outcome: str
    remote_task_id: str | None = None
    next_phase: str | None = None


Step = Callable[[KnowledgeProviderOperation], Awaitable[str | StepResult]]


@dataclass(frozen=True)
class ProviderHandlers:
    # Owners must check current authorization and target fences, verify receipts,
    # and implement idempotent projection. A bare HTTP 200 is not 'confirmed'.
    send: Step
    reconcile: Step
    project: Step

    def __post_init__(self):
        if not all(callable(step) for step in (self.send, self.reconcile, self.project)):
            raise ValueError("incomplete provider operation handler")


# Registered when the task module loads in both dispatchers and workers, not
# as a side effect of a web request. No database or provider I/O at startup.
from bisheng.knowledge.application.provider_provision_runtime import register_provision_handlers

PROVIDER_HANDLERS: dict[str, ProviderHandlers] = {}
register_provision_handlers(PROVIDER_HANDLERS, ProviderHandlers)


def utcnow():
    return datetime.now(UTC).replace(tzinfo=None)


async def advance_one(
    *,
    tenant_id,
    operation_id,
    expected_revision,
    attempt_budget,
    claim,
    send,
    reconcile,
    project,
    advance,
    step_timeout=None,
):
    row = await claim(tenant_id=tenant_id, operation_id=operation_id, expected_revision=expected_revision)
    if row is None:
        return False
    if (row.tenant_id, row.operation_id, row.revision) != (
        tenant_id,
        operation_id,
        expected_revision + 1,
    ) or not row.lease_token:
        raise RuntimeError("claimed operation disagrees with wakeup")
    # "pending" means "proven not sent yet" (a replay after verified absence), so
    # it must re-send. Leaving it out of this map made every replay die on a
    # KeyError before the send step ever ran.
    step = {
        "pending": send,
        "sending": send,
        "waiting_remote": reconcile,
        "reconciling": reconcile,
        "applying": project,
    }[row.state]
    try:
        async with asyncio.timeout(step_timeout if step_timeout is not None else step_timeout_seconds()):
            result = await step(row)
    except Exception as exc:
        # Provider exceptions can contain credentials or response bodies. Keep
        # only their type. A send exception is *not* proof of non-execution.
        logger.warning(
            "provider step uncertain operation={} phase={} error_type={}", operation_id, row.phase, type(exc).__name__
        )
        result = "unknown"
    if isinstance(result, str):
        result = StepResult(result)
    kwargs = {}
    if not isinstance(result, StepResult):
        raise ValueError("unrecognized provider result")
    outcome = result.outcome
    if outcome == "confirmed":
        state = "succeeded" if row.state == "applying" else "applying"
    elif outcome == "checkpoint" and row.state == "applying" and result.next_phase:
        state = "applying"
        kwargs["next_phase"] = result.next_phase
    elif outcome == "accepted" and row.state != "applying" and (result.remote_task_id or row.remote_task_id):
        state = "waiting_remote"
        if result.remote_task_id:
            kwargs["remote_task_id"] = result.remote_task_id
    elif outcome == "verified_safe_replay" and row.state == "reconciling":
        state = "pending"
    elif outcome == "rejected":
        state = "failed"
    elif outcome == "unknown":
        state = "applying" if row.state == "applying" else "reconciling"
    else:
        state = "manual_review"
    if outcome in {"unknown", "verified_safe_replay", "accepted"} and row.attempt >= attempt_budget:
        state = "manual_review"
    return await advance(row, state=state, **kwargs)


async def _execute(tenant_id, operation_id, expected_revision):
    repo = ProviderOperationRepository()
    # The signal's ambient tenant (including its legacy default) is not proof.
    # Only read routing fields, constrained by BOTH header and durable ID.
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            target = await repo.message_target(session, tenant_id=tenant_id, operation_id=operation_id)
    if target is None or target.tenant_id != tenant_id or target.revision != expected_revision:
        return False
    handlers = PROVIDER_HANDLERS.get(target.kind)
    if not isinstance(handlers, ProviderHandlers):
        logger.warning("provider handler unavailable; not claiming operation={} kind={}", operation_id, target.kind)
        return False

    async def claim(**identity):
        async with get_async_db_session() as session:
            row = await repo.claim_instance_slot(
                session,
                **identity,
                instance_id=target.provider_instance_id,
                kind=target.kind,
                concurrency=INSTANCE_CONCURRENCY,
                clock=utcnow,
                lease_seconds=lease_seconds(),
            )
            if row is not None:
                session.expunge(row)
            await session.commit()
            return row

    async def advance(row, *, state, **kwargs):
        now = utcnow()
        retry = state in {"waiting_remote", "reconciling", "pending"} or (
            state == row.state == "applying" and not kwargs.get("next_phase")
        )
        delay = random.uniform(1, min(300, 2 ** min(9, row.attempt))) if retry else 0
        async with get_async_db_session() as session:
            changed = await repo.apply(
                session,
                tenant_id=tenant_id,
                operation_id=operation_id,
                expected_revision=row.revision,
                lease_token=row.lease_token,
                generation=row.generation,
                operation_epoch=row.operation_epoch,
                now=now,
                next_attempt_at=now + timedelta(seconds=delay),
                state=state,
                last_error_code="manual_review_required" if state == "manual_review" else None,
                **kwargs,
            )
            await session.commit()
        if changed and state == "manual_review":
            logger.warning(
                "provider operation requires review tenant={} operation={} phase={}", tenant_id, operation_id, row.phase
            )
        if changed and should_chain_wakeup(state=state, delay=delay):
            # A phase transition (send confirmed -> applying, checkpoint -> applying)
            # is due immediately; waiting for the 30s sweep here is what made a
            # created space appear in the provider a minute late.
            wake_provider_operation(tenant_id=tenant_id, operation_id=operation_id, expected_revision=row.revision + 1)
        return changed

    with tenant_execution_scope(target.tenant_id):
        return await advance_one(
            tenant_id=tenant_id,
            operation_id=operation_id,
            expected_revision=expected_revision,
            attempt_budget=ATTEMPT_BUDGET,
            claim=claim,
            send=handlers.send,
            reconcile=handlers.reconcile,
            project=handlers.project,
            advance=advance,
        )


@bisheng_celery.task(bind=True, queue="knowledge_celery")
def advance_provider_operation(self, operation_id: str, expected_revision: int):
    tenant_id = (self.request.headers or {}).get("tenant_id")
    if type(tenant_id) is not int or tenant_id <= 0 or type(expected_revision) is not int or expected_revision < 1:
        raise ValueError("explicit tenant header and positive message revision required")
    return run_async_task(lambda: _execute(tenant_id, operation_id, expected_revision))
