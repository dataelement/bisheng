from __future__ import annotations

from collections.abc import Callable

from loguru import logger

from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery

COMPENSATION_BATCH_SIZE = 100
RECONCILE_BATCH_SIZE = 100
DEFAULT_HEARTBEAT_TIMEOUT_SECONDS = 900
_TASK_OPTIONS = {
    "acks_late": True,
    "autoretry_for": (Exception,),
    "retry_backoff": True,
    "retry_jitter": True,
    "retry_kwargs": {"max_retries": 8},
    "queue": "knowledge_celery",
    "time_limit": 900,
    "soft_time_limit": 840,
}


@bisheng_celery.task(
    bind=True,
    name="bisheng.worker.knowledge.file_change_tasks.coordinate_file_change_execution",
    **_TASK_OPTIONS,
)
def coordinate_file_change_execution(
    self,
    *,
    request_id: int,
    execution_token: str | None = None,
) -> dict:
    return _run_in_task_tenant(
        request=self.request,
        coroutine_factory=lambda tenant_id: _coordinate_execution_async(
            tenant_id=tenant_id,
            request_id=int(request_id),
            execution_token=str(execution_token) if execution_token else None,
        ),
    )


@bisheng_celery.task(
    bind=True,
    name="bisheng.worker.knowledge.file_change_tasks.watchdog_file_change_execution",
    **_TASK_OPTIONS,
)
def watchdog_file_change_execution(
    self,
    *,
    request_id: int,
    execution_token: str,
    heartbeat_timeout_seconds: int = DEFAULT_HEARTBEAT_TIMEOUT_SECONDS,
) -> dict:
    return _run_in_task_tenant(
        request=self.request,
        coroutine_factory=lambda tenant_id: _watchdog_execution_async(
            tenant_id=tenant_id,
            request_id=int(request_id),
            execution_token=str(execution_token),
            heartbeat_timeout_seconds=int(heartbeat_timeout_seconds),
        ),
    )


@bisheng_celery.task(
    bind=True,
    name="bisheng.worker.knowledge.file_change_tasks.execute_file_change_step",
    **_TASK_OPTIONS,
)
def execute_file_change_step(
    self,
    *,
    request_id: int,
    execution_token: str,
    action: str,
    step_code: str,
    idempotency_key: str,
) -> dict:
    return _run_in_task_tenant(
        request=self.request,
        coroutine_factory=lambda tenant_id: _execute_step_async(
            tenant_id=tenant_id,
            request_id=int(request_id),
            execution_token=str(execution_token),
            action=str(action),
            step_code=str(step_code),
            idempotency_key=str(idempotency_key),
        ),
    )


@bisheng_celery.task(
    bind=True,
    name="bisheng.worker.knowledge.file_change_tasks.acknowledge_file_change_upload_pipeline",
    **_TASK_OPTIONS,
)
def acknowledge_file_change_upload_pipeline(
    self,
    *,
    request_id: int,
    execution_token: str,
    file_id: int,
) -> dict:
    return _run_in_task_tenant(
        request=self.request,
        coroutine_factory=lambda tenant_id: _acknowledge_upload_pipeline_async(
            tenant_id=tenant_id,
            request_id=int(request_id),
            execution_token=str(execution_token),
            file_id=int(file_id),
        ),
    )


@bisheng_celery.task(
    bind=True,
    name="bisheng.worker.knowledge.file_change_tasks.cleanup_file_change_upload_stage",
    **_TASK_OPTIONS,
)
def cleanup_file_change_upload_stage(
    self,
    *,
    request_id: int,
    upload_id: str,
    terminal_action: str,
    reason: str | None = None,
) -> dict:
    return _run_in_task_tenant(
        request=self.request,
        coroutine_factory=lambda tenant_id: _cleanup_upload_stage_async(
            tenant_id=tenant_id,
            request_id=int(request_id),
            upload_id=str(upload_id),
            terminal_action=str(terminal_action),
            reason=reason,
        ),
    )


@bisheng_celery.task(
    bind=True,
    name="bisheng.worker.knowledge.file_change_tasks.cleanup_orphan_file_change_upload_stage",
    **_TASK_OPTIONS,
)
def cleanup_orphan_file_change_upload_stage(self, *, upload_id: str) -> dict:
    return _run_in_task_tenant(
        request=self.request,
        coroutine_factory=lambda tenant_id: _cleanup_orphan_upload_stage_async(
            tenant_id=tenant_id,
            upload_id=str(upload_id),
        ),
    )


@bisheng_celery.task(
    bind=True,
    name="bisheng.worker.knowledge.file_change_tasks.purge_file_change_delete",
    **_TASK_OPTIONS,
)
def purge_file_change_delete(self, *, request_id: int, execution_token: str) -> dict:
    return _run_in_task_tenant(
        request=self.request,
        coroutine_factory=lambda tenant_id: _run_owner_async(
            tenant_id=tenant_id,
            request_id=int(request_id),
            execution_token=str(execution_token),
            method="purge_delete",
            success="purged",
        ),
    )


@bisheng_celery.task(
    bind=True,
    name="bisheng.worker.knowledge.file_change_tasks.cleanup_file_change_mutation",
    **_TASK_OPTIONS,
)
def cleanup_file_change_mutation(self, *, request_id: int, execution_token: str) -> dict:
    return _run_in_task_tenant(
        request=self.request,
        coroutine_factory=lambda tenant_id: _run_owner_async(
            tenant_id=tenant_id,
            request_id=int(request_id),
            execution_token=str(execution_token),
            method="continue_post_cutover_cleanup",
            success="cleaned",
        ),
    )


@bisheng_celery.task(
    bind=True,
    name="bisheng.worker.knowledge.file_change_tasks.continue_file_change_compensation",
    **_TASK_OPTIONS,
)
def continue_file_change_compensation(self, *, request_id: int, execution_token: str) -> dict:
    return _run_in_task_tenant(
        request=self.request,
        coroutine_factory=lambda tenant_id: _run_owner_async(
            tenant_id=tenant_id,
            request_id=int(request_id),
            execution_token=str(execution_token),
            method="continue_compensation",
            success="compensated",
        ),
    )


@bisheng_celery.task(
    bind=True,
    name="bisheng.worker.knowledge.file_change_tasks.watchdog_tenant_file_change_executions",
    **_TASK_OPTIONS,
)
def watchdog_tenant_file_change_executions(self, *, after_request_id: int = 0) -> dict:
    return _run_in_task_tenant(
        request=self.request,
        coroutine_factory=lambda tenant_id: _watchdog_tenant_page_async(
            tenant_id=tenant_id,
            after_request_id=int(after_request_id),
        ),
    )


@bisheng_celery.task(
    name="bisheng.worker.knowledge.file_change_tasks.watchdog_all_file_change_executions",
    **_TASK_OPTIONS,
)
def watchdog_all_file_change_executions() -> dict:
    return run_async_task(
        lambda: _coordinate_all_tenants_async(
            tenant_task=watchdog_tenant_file_change_executions,
            initial_kwargs={"after_request_id": 0},
        )
    )


@bisheng_celery.task(
    bind=True,
    name="bisheng.worker.knowledge.file_change_tasks.compensate_tenant_file_change_execution_steps",
    **_TASK_OPTIONS,
)
def compensate_tenant_file_change_execution_steps(self, *, after_step_id: int = 0) -> dict:
    return _run_in_task_tenant(
        request=self.request,
        coroutine_factory=lambda tenant_id: _compensate_tenant_step_page_async(
            tenant_id=tenant_id,
            after_step_id=int(after_step_id),
        ),
    )


@bisheng_celery.task(
    name="bisheng.worker.knowledge.file_change_tasks.compensate_all_file_change_execution_steps",
    **_TASK_OPTIONS,
)
def compensate_all_file_change_execution_steps() -> dict:
    return run_async_task(
        lambda: _coordinate_all_tenants_async(
            tenant_task=compensate_tenant_file_change_execution_steps,
            initial_kwargs={"after_step_id": 0},
        )
    )


@bisheng_celery.task(
    bind=True,
    name="bisheng.worker.knowledge.file_change_tasks.cleanup_tenant_file_change_residue",
    **_TASK_OPTIONS,
)
def cleanup_tenant_file_change_residue(
    self,
    *,
    after_request_id: int = 0,
    after_stage_id: int = 0,
) -> dict:
    return _run_in_task_tenant(
        request=self.request,
        coroutine_factory=lambda tenant_id: _cleanup_tenant_page_async(
            tenant_id=tenant_id,
            after_request_id=int(after_request_id),
            after_stage_id=int(after_stage_id),
        ),
    )


@bisheng_celery.task(
    name="bisheng.worker.knowledge.file_change_tasks.cleanup_all_file_change_residue",
    **_TASK_OPTIONS,
)
def cleanup_all_file_change_residue() -> dict:
    return run_async_task(
        lambda: _coordinate_all_tenants_async(
            tenant_task=cleanup_tenant_file_change_residue,
            initial_kwargs={"after_request_id": 0, "after_stage_id": 0},
        )
    )


@bisheng_celery.task(
    bind=True,
    name="bisheng.worker.knowledge.file_change_tasks.reconcile_space_file_change_approvers",
    **_TASK_OPTIONS,
)
def reconcile_space_file_change_approvers(
    self,
    *,
    space_id: int,
    reason: str = "permission_event",
) -> dict:
    return _run_in_task_tenant(
        request=self.request,
        coroutine_factory=lambda tenant_id: _reconcile_space_async(
            tenant_id=tenant_id,
            space_id=int(space_id),
            reason=str(reason),
        ),
    )


@bisheng_celery.task(
    bind=True,
    name="bisheng.worker.knowledge.file_change_tasks.reconcile_tenant_file_change_approvers",
    **_TASK_OPTIONS,
)
def reconcile_tenant_file_change_approvers(
    self,
    *,
    after_update_time: str | None = None,
    after_request_id: int = 0,
) -> dict:
    return _run_in_task_tenant(
        request=self.request,
        coroutine_factory=lambda tenant_id: _reconcile_tenant_page_async(
            tenant_id=tenant_id,
            after_update_time=after_update_time,
            after_request_id=int(after_request_id),
        ),
    )


@bisheng_celery.task(
    name="bisheng.worker.knowledge.file_change_tasks.reconcile_all_file_change_approvers",
    **_TASK_OPTIONS,
)
def reconcile_all_file_change_approvers() -> dict:
    return run_async_task(_coordinate_reconcile_all_tenants_async)


class CeleryKnowledgeSpaceFileChangeDispatcher:
    """Decision-delivery adapter that exposes only the stable business request id."""

    async def dispatch(self, *, tenant_id: int, request_id: int) -> None:
        if isinstance(tenant_id, bool) or isinstance(request_id, bool) or int(tenant_id) <= 0 or int(request_id) <= 0:
            raise ValueError("F046 dispatcher requires positive tenant_id and request_id")
        coordinate_file_change_execution.apply_async(
            kwargs={"request_id": int(request_id)},
            headers={"tenant_id": int(tenant_id)},
        )


async def _coordinate_execution_async(
    *,
    tenant_id: int,
    request_id: int,
    execution_token: str | None,
) -> dict:
    from bisheng.knowledge.domain.services.knowledge_space_mutation_executor import (
        MutationExecutionCompleted,
    )

    from bisheng.common.errcode.base import BaseErrorCode

    coordinator = _build_execution_coordinator()
    executor = _build_mutation_executor()
    try:
        prepared = await executor.prepare_execution(request_id=int(request_id))
    except BaseErrorCode as exc:
        # A deterministic business-rule violation raised while preparing the
        # approved change — e.g. the applicant no longer holds the required
        # permission (SpacePermissionDeniedError), or the target already has a
        # same-name/same-content file (SpaceFileDuplicateError /
        # SpaceFileNameDuplicateError). These never succeed on retry, and leaving
        # the request in `queued` hides the failure forever (nothing re-drives a
        # queued request). Fail it terminally so the error surfaces and the
        # client stops showing 等待执行. Infra/transient errors are NOT BaseErrorCode
        # and still propagate to Celery autoretry.
        transitioned = await executor.fail_unstarted_request(
            request_id=int(request_id),
            failure_reason=f"file change cannot be applied: {exc}",
        )
        logger.warning(
            "F046 coordinate permanently failed ({}): request_id={} transitioned_to_failed={}",
            type(exc).__name__,
            request_id,
            transitioned,
        )
        return {"status": "failed", "reason": "business_rule_violation"}
    if isinstance(prepared, MutationExecutionCompleted):
        return {"status": "completed"}
    if execution_token and str(execution_token) != str(prepared.execution_token):
        return {"status": "ignored"}
    identity = await coordinator.load_identity_by_request(
        tenant_id=int(tenant_id),
        request_id=int(request_id),
        execution_token=str(prepared.execution_token),
    )
    if identity is None:
        return {"status": "ignored"}
    await coordinator.dispatch_ready_steps(identity=identity, dispatcher=_dispatch_file_change_step)
    return {"status": str(await coordinator.reconcile(identity=identity))}


async def _reconcile_space_async(*, tenant_id: int, space_id: int, reason: str) -> dict:
    reconciled = await _build_approver_reconcile_dispatcher().reconcile_space(
        tenant_id=int(tenant_id),
        space_id=int(space_id),
        reason=str(reason),
    )
    return {"reconciled": int(reconciled)}


async def _reconcile_tenant_page_async(
    *,
    tenant_id: int,
    after_update_time: str | None,
    after_request_id: int,
) -> dict:
    from datetime import datetime

    from bisheng.core.database import get_async_db_session
    from bisheng.knowledge.domain.repositories.knowledge_space_file_change_request_repository import (
        KnowledgeSpaceFileChangeRequestRepository,
    )

    cursor_time = datetime.fromisoformat(after_update_time) if after_update_time else None
    async with get_async_db_session() as session:
        candidates, has_more = await KnowledgeSpaceFileChangeRequestRepository(session).list_reconcile_candidates(
            tenant_id=int(tenant_id),
            after_update_time=cursor_time,
            after_request_id=int(after_request_id),
            limit=RECONCILE_BATCH_SIZE,
        )
    space_ids = sorted({int(candidate.space_id) for candidate in candidates})
    dispatcher = _build_approver_reconcile_dispatcher()
    reconciled, failed = 0, 0
    for space_id in space_ids:
        try:
            reconciled += int(
                await dispatcher.reconcile_space(
                    tenant_id=int(tenant_id),
                    space_id=space_id,
                    reason="beat",
                )
            )
        except Exception:
            failed += 1
            logger.exception("F046 approver reconciliation failed for space_id={}", space_id)
    if has_more:
        last = candidates[-1]
        reconcile_tenant_file_change_approvers.apply_async(
            kwargs={
                "after_update_time": last.update_time.isoformat(),
                "after_request_id": int(last.request_id),
            },
            headers={"tenant_id": int(tenant_id)},
        )
    return {
        "processed": len(space_ids),
        "reconciled": reconciled,
        "failed": failed,
        "has_more": bool(has_more),
    }


async def _coordinate_reconcile_all_tenants_async() -> dict:
    tenant_ids = await _load_active_tenant_ids()
    dispatched, failed = 0, 0
    for tenant_id in tenant_ids:
        try:
            reconcile_tenant_file_change_approvers.apply_async(
                kwargs={"after_update_time": None, "after_request_id": 0},
                headers={"tenant_id": int(tenant_id)},
            )
            dispatched += 1
        except Exception:
            failed += 1
            logger.exception("F046 tenant approver reconciliation dispatch failed for tenant_id={}", tenant_id)
    return {"processed": len(tenant_ids), "dispatched": dispatched, "failed": failed}


async def _watchdog_execution_async(
    *,
    tenant_id: int,
    request_id: int,
    execution_token: str,
    heartbeat_timeout_seconds: int,
) -> dict:
    if heartbeat_timeout_seconds <= 0:
        raise ValueError("F046 watchdog heartbeat timeout must be positive")
    coordinator = _build_execution_coordinator()
    identity = await coordinator.load_identity_by_request(
        tenant_id=int(tenant_id),
        request_id=int(request_id),
        execution_token=str(execution_token),
    )
    if identity is None:
        return {"status": "ignored"}
    failed = await coordinator.fail(
        identity=identity,
        error_summary="business execution watchdog timeout",
        watchdog=True,
        heartbeat_timeout_seconds=int(heartbeat_timeout_seconds),
    )
    return {"status": "failed" if failed else "running"}


async def _dispatch_file_change_step(context) -> str:
    execute_file_change_step.apply_async(
        kwargs={
            "request_id": int(context.request_id),
            "execution_token": str(context.execution_token),
            "action": str(context.action),
            "step_code": str(context.step_code),
            "idempotency_key": str(context.idempotency_key),
        },
        task_id=str(context.idempotency_key),
        headers={"tenant_id": int(context.tenant_id)},
    )
    return str(context.idempotency_key)


async def _execute_step_async(**kwargs) -> dict:
    from bisheng.knowledge.domain.services.knowledge_space_file_change_execution_coordinator import (
        ExecutionReconcileStatus,
    )

    coordinator = _build_execution_coordinator()
    identity = await coordinator.load_identity_by_request(
        tenant_id=int(kwargs["tenant_id"]),
        request_id=int(kwargs["request_id"]),
        execution_token=str(kwargs["execution_token"]),
    )
    if identity is None:
        return {"status": "ignored"}
    status = await coordinator.acknowledge_step(
        identity=identity,
        step_code=str(kwargs["step_code"]),
        verifier=_build_mutation_executor().execute_and_verify_step,
    )
    # Self-propel the saga. A step that completes while the request is still
    # RUNNING means the next step is now ready, but nothing has dispatched it:
    # acknowledge_step only reconciles (completion check), and the actual
    # dispatch_ready_steps runs solely inside the coordinate task. Without this
    # hand-off the next step would wait for the periodic ~60s watchdog, so a
    # multi-step rename/move/delete/upload drags out to tens of seconds even
    # though each step takes ~1s. Re-enqueue coordination (bound to the current
    # execution_token so a superseded generation is ignored) to dispatch the
    # next ready step immediately; the watchdog stays as the safety net if this
    # hand-off is ever lost.
    if status == ExecutionReconcileStatus.RUNNING:
        coordinate_file_change_execution.apply_async(
            kwargs={
                "request_id": int(kwargs["request_id"]),
                "execution_token": str(kwargs["execution_token"]),
            },
            headers={"tenant_id": int(kwargs["tenant_id"])},
        )
    return {"status": str(status)}


async def _acknowledge_upload_pipeline_async(
    *,
    tenant_id: int,
    request_id: int,
    execution_token: str,
    file_id: int,
) -> dict:
    coordinator = _build_execution_coordinator()
    identity = await coordinator.load_identity_by_request(
        tenant_id=int(tenant_id),
        request_id=int(request_id),
        execution_token=str(execution_token),
    )
    if identity is None:
        return {"status": "ignored"}
    status = await coordinator.acknowledge_step(
        identity=identity,
        step_code="upload.parse",
        verifier=_build_mutation_executor().execute_and_verify_step,
        acknowledgement={"file_id": int(file_id)},
    )
    return {"status": str(status)}


async def _cleanup_upload_stage_async(
    *,
    tenant_id: int,
    request_id: int,
    upload_id: str,
    terminal_action: str,
    reason: str | None,
) -> dict:
    request = await _build_file_change_service().cleanup(
        tenant_id=int(tenant_id),
        request_id=int(request_id),
        upload_id=str(upload_id),
        terminal_action=str(terminal_action),
        reason=reason,
    )
    return {"cleanup_state": str(request.cleanup_state)}


async def _cleanup_orphan_upload_stage_async(*, tenant_id: int, upload_id: str) -> dict:
    del tenant_id
    reconciled = await (await _build_upload_stage_service()).reconcile_lifecycle(str(upload_id))
    return {"status": "reconciled" if reconciled else "ignored"}


async def _run_owner_async(
    *,
    tenant_id: int,
    request_id: int,
    execution_token: str,
    method: str,
    success: str,
) -> dict:
    del tenant_id
    operation = getattr(_build_mutation_executor(), method)
    verified = await operation(request_id=int(request_id), execution_token=str(execution_token))
    if not verified:
        raise RuntimeError(f"F046 {method} is not verified complete")
    return {"status": success}


async def _watchdog_tenant_page_async(*, tenant_id: int, after_request_id: int) -> dict:
    page = await _build_compensation_service().list_watchdog_page(
        tenant_id=int(tenant_id),
        after_request_id=int(after_request_id),
        limit=COMPENSATION_BATCH_SIZE,
    )
    dispatched, failed = 0, 0
    for candidate in page.items:
        try:
            watchdog_file_change_execution.apply_async(
                kwargs={
                    "request_id": int(candidate.request_id),
                    "execution_token": str(candidate.execution_token),
                },
                headers={"tenant_id": int(tenant_id)},
            )
            dispatched += 1
        except Exception:
            failed += 1
            logger.exception("F046 watchdog dispatch failed for request_id={}", candidate.request_id)
    if page.has_more:
        _require_advanced_id_cursor(after_request_id, page.next_after_id, "request")
        watchdog_tenant_file_change_executions.apply_async(
            kwargs={"after_request_id": int(page.next_after_id)},
            headers={"tenant_id": int(tenant_id)},
        )
    return {"processed": len(page.items), "dispatched": dispatched, "failed": failed, "has_more": page.has_more}


async def _compensate_tenant_step_page_async(*, tenant_id: int, after_step_id: int) -> dict:
    from bisheng.knowledge.domain.models.knowledge_space_file_change_request import (
        KnowledgeSpaceFileChangeExecutionState,
    )

    page = await _build_compensation_service().list_step_recovery_page(
        tenant_id=int(tenant_id),
        after_step_id=int(after_step_id),
        limit=COMPENSATION_BATCH_SIZE,
    )
    dispatched, failed = 0, 0
    seen: set[tuple[int, str, str]] = set()
    for candidate in page.items:
        generation = (int(candidate.request_id), str(candidate.execution_token), str(candidate.execution_state))
        if generation in seen:
            continue
        seen.add(generation)
        task = (
            continue_file_change_compensation
            if candidate.execution_state == KnowledgeSpaceFileChangeExecutionState.COMPENSATING
            else coordinate_file_change_execution
        )
        try:
            task.apply_async(
                kwargs={
                    "request_id": int(candidate.request_id),
                    "execution_token": str(candidate.execution_token),
                },
                headers={"tenant_id": int(tenant_id)},
            )
            dispatched += 1
        except Exception:
            failed += 1
            logger.exception("F046 recovery dispatch failed for request_id={}", candidate.request_id)
    if page.has_more:
        _require_advanced_id_cursor(after_step_id, page.next_after_id, "step")
        compensate_tenant_file_change_execution_steps.apply_async(
            kwargs={"after_step_id": int(page.next_after_id)},
            headers={"tenant_id": int(tenant_id)},
        )
    return {"processed": len(page.items), "dispatched": dispatched, "failed": failed, "has_more": page.has_more}


async def _cleanup_tenant_page_async(*, tenant_id: int, after_request_id: int, after_stage_id: int) -> dict:
    service = _build_compensation_service()
    page = await service.list_cleanup_page(
        tenant_id=int(tenant_id),
        after_request_id=int(after_request_id),
        limit=COMPENSATION_BATCH_SIZE,
    )
    stage_page = await service.list_expired_orphan_stage_page(
        tenant_id=int(tenant_id),
        after_stage_id=int(after_stage_id),
        limit=COMPENSATION_BATCH_SIZE,
    )
    dispatched, failed = 0, 0
    tasks = {
        "stage": cleanup_file_change_upload_stage,
        "delete_purge": purge_file_change_delete,
        "mutation_cleanup": cleanup_file_change_mutation,
    }
    for candidate in page.items:
        kwargs = {"request_id": int(candidate.request_id)}
        if candidate.kind == "stage":
            kwargs.update(upload_id=str(candidate.upload_id), terminal_action=str(candidate.terminal_action))
        else:
            kwargs["execution_token"] = str(candidate.execution_token)
        try:
            tasks[candidate.kind].apply_async(kwargs=kwargs, headers={"tenant_id": int(tenant_id)})
            dispatched += 1
        except Exception:
            failed += 1
            logger.exception("F046 residue dispatch failed for request_id={}", candidate.request_id)
    for candidate in stage_page.items:
        try:
            cleanup_orphan_file_change_upload_stage.apply_async(
                kwargs={"upload_id": str(candidate.upload_id)},
                headers={"tenant_id": int(tenant_id)},
            )
            dispatched += 1
        except Exception:
            failed += 1
            logger.exception("F046 stage dispatch failed for stage_id={}", candidate.stage_id)
    if page.has_more or stage_page.has_more:
        cleanup_tenant_file_change_residue.apply_async(
            kwargs={
                "after_request_id": int(page.next_after_id),
                "after_stage_id": int(stage_page.next_after_id),
            },
            headers={"tenant_id": int(tenant_id)},
        )
    return {
        "processed": len(page.items) + len(stage_page.items),
        "dispatched": dispatched,
        "failed": failed,
        "has_more": bool(page.has_more or stage_page.has_more),
    }


async def _coordinate_all_tenants_async(*, tenant_task, initial_kwargs: dict) -> dict:
    tenant_ids = await _load_active_tenant_ids()
    dispatched = 0
    for tenant_id in tenant_ids:
        tenant_task.apply_async(kwargs=dict(initial_kwargs), headers={"tenant_id": int(tenant_id)})
        dispatched += 1
    return {"processed": len(tenant_ids), "dispatched": dispatched}


async def _load_active_tenant_ids() -> list[int]:
    from sqlmodel import select

    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.core.database import get_async_db_session
    from bisheng.database.models.tenant import Tenant

    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            rows = await session.exec(select(Tenant.id).where(Tenant.status == "active").order_by(Tenant.id))
            return [int(row) for row in rows.all()]


def _build_execution_coordinator():
    from bisheng.knowledge.domain.services.knowledge_space_file_change_execution_coordinator import (
        KnowledgeSpaceFileChangeExecutionCoordinator,
    )

    return KnowledgeSpaceFileChangeExecutionCoordinator()


def _build_mutation_executor():
    from bisheng.knowledge.domain.services.knowledge_space_mutation_executor import KnowledgeSpaceMutationExecutor

    return KnowledgeSpaceMutationExecutor()


def _build_compensation_service():
    from bisheng.knowledge.domain.services.knowledge_space_file_change_compensation_service import (
        KnowledgeSpaceFileChangeCompensationService,
    )

    return KnowledgeSpaceFileChangeCompensationService()


def _build_approver_reconcile_dispatcher():
    from bisheng.permission.domain.services.file_change_approver_reconcile_dispatcher import (
        FileChangeApproverReconcileDispatcher,
    )

    return FileChangeApproverReconcileDispatcher()


def _build_file_change_service():
    from bisheng.knowledge.domain.services.knowledge_space_file_change_terminal_cleanup_service import (
        KnowledgeSpaceFileChangeTerminalCleanupService,
    )

    return KnowledgeSpaceFileChangeTerminalCleanupService()


async def _build_upload_stage_service():
    from bisheng.core.storage.minio.minio_manager import get_minio_storage
    from bisheng.knowledge.domain.services.knowledge_space_upload_stage_service import (
        KnowledgeSpaceUploadStageService,
    )

    async def unused_capacity(_tenant_id: int, _user_id: int):
        raise RuntimeError("capacity loading is not used by lifecycle cleanup")

    return KnowledgeSpaceUploadStageService(
        storage=await get_minio_storage(),
        capacity_loader=unused_capacity,
    )


def _run_in_task_tenant(*, request, coroutine_factory: Callable[[int], object]):
    tenant_id = _require_tenant_id_header(request)
    token = set_current_tenant_id(tenant_id)
    try:
        return run_async_task(lambda: coroutine_factory(tenant_id))
    finally:
        current_tenant_id.reset(token)


def _require_tenant_id_header(request) -> int:
    headers = getattr(request, "headers", None) or {}
    raw_tenant_id = headers.get("tenant_id")
    if raw_tenant_id is None or isinstance(raw_tenant_id, bool):
        raise ValueError("F046 worker requires a positive tenant_id header")
    try:
        tenant_id = int(raw_tenant_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("F046 worker requires a positive tenant_id header") from exc
    if tenant_id <= 0:
        raise ValueError("F046 worker requires a positive tenant_id header")
    return tenant_id


def _require_advanced_id_cursor(current_id: int, next_id: int, cursor_name: str) -> None:
    if int(next_id) <= int(current_id):
        raise RuntimeError(f"F046 {cursor_name} cursor did not advance")
