from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from loguru import logger

from bisheng.approval.domain.services.approval_runtime_handler_factory import build_runtime_handler
from bisheng.core.context.tenant import (
    DEFAULT_TENANT_ID,
    bypass_tenant_filter,
    current_tenant_id,
    set_current_tenant_id,
)
from bisheng.knowledge.domain.services.knowledge_space_file_change_scenario_handler import (
    FILE_CHANGE_SCENARIO_CODE,
)
from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery

RECONCILE_BATCH_SIZE = 100
COMPENSATION_BATCH_SIZE = 100
DEFAULT_DEFERRED_HEARTBEAT_TIMEOUT_SECONDS = 900
_RETRY_OPTIONS = {
    "autoretry_for": (Exception,),
    "retry_backoff": True,
    "retry_jitter": True,
    "retry_kwargs": {"max_retries": 8},
}


@bisheng_celery.task(
    bind=True,
    acks_late=True,
    time_limit=900,
    soft_time_limit=840,
    name="bisheng.worker.approval.file_change_tasks.coordinate_file_change_execution",
    **_RETRY_OPTIONS,
)
def coordinate_file_change_execution(
    self,
    *,
    outbox_id: int,
    execution_token: str,
) -> dict:
    """Resume one current Deferred generation from its durable identity."""

    return _run_in_task_tenant(
        request=self.request,
        coroutine_factory=lambda tenant_id: _coordinate_execution_async(
            tenant_id=tenant_id,
            outbox_id=int(outbox_id),
            execution_token=str(execution_token),
        ),
    )


@bisheng_celery.task(
    bind=True,
    acks_late=True,
    time_limit=900,
    soft_time_limit=840,
    name="bisheng.worker.approval.file_change_tasks.watchdog_file_change_execution",
    **_RETRY_OPTIONS,
)
def watchdog_file_change_execution(
    self,
    *,
    outbox_id: int,
    execution_token: str,
    heartbeat_timeout_seconds: int = DEFAULT_DEFERRED_HEARTBEAT_TIMEOUT_SECONDS,
) -> dict:
    """Fail only the still-current Deferred token after its timeout check."""

    return _run_in_task_tenant(
        request=self.request,
        coroutine_factory=lambda tenant_id: _watchdog_execution_async(
            tenant_id=tenant_id,
            outbox_id=int(outbox_id),
            execution_token=str(execution_token),
            heartbeat_timeout_seconds=int(heartbeat_timeout_seconds),
        ),
    )


@bisheng_celery.task(
    bind=True,
    acks_late=True,
    time_limit=900,
    soft_time_limit=840,
    name="bisheng.worker.approval.file_change_tasks.execute_file_change_step",
    **_RETRY_OPTIONS,
)
def execute_file_change_step(
    self,
    *,
    request_id: int,
    instance_id: int,
    outbox_id: int,
    execution_token: str,
    action: str,
    step_code: str,
    idempotency_key: str,
) -> dict:
    """Delegate a durable external step to the Knowledge owner Service."""

    return _run_in_task_tenant(
        request=self.request,
        coroutine_factory=lambda tenant_id: _execute_step_async(
            tenant_id=tenant_id,
            request_id=int(request_id),
            instance_id=int(instance_id),
            outbox_id=int(outbox_id),
            execution_token=str(execution_token),
            action=str(action),
            step_code=str(step_code),
            idempotency_key=str(idempotency_key),
        ),
    )


@bisheng_celery.task(
    bind=True,
    acks_late=True,
    time_limit=900,
    soft_time_limit=840,
    name="bisheng.worker.approval.file_change_tasks.acknowledge_file_change_upload_pipeline",
    **_RETRY_OPTIONS,
)
def acknowledge_file_change_upload_pipeline(
    self,
    *,
    request_id: int,
    execution_token: str,
    file_id: int,
) -> dict:
    """Acknowledge parser/index/vector only after authoritative read-back."""

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
    acks_late=True,
    time_limit=900,
    soft_time_limit=840,
    name="bisheng.worker.approval.file_change_tasks.cleanup_file_change_upload_stage",
    **_RETRY_OPTIONS,
)
def cleanup_file_change_upload_stage(
    self,
    *,
    request_id: int,
    upload_id: str,
    terminal_action: str,
    reason: str | None = None,
) -> dict:
    """Retry terminal stage cleanup without creating a delete approval."""

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
    acks_late=True,
    time_limit=900,
    soft_time_limit=840,
    name="bisheng.worker.approval.file_change_tasks.cleanup_orphan_file_change_upload_stage",
    **_RETRY_OPTIONS,
)
def cleanup_orphan_file_change_upload_stage(
    self,
    *,
    upload_id: str,
) -> dict:
    """Reconcile one lifecycle-managed stage without deleting its object."""

    return _run_in_task_tenant(
        request=self.request,
        coroutine_factory=lambda tenant_id: _cleanup_orphan_upload_stage_async(
            tenant_id=tenant_id,
            upload_id=str(upload_id),
        ),
    )


@bisheng_celery.task(
    bind=True,
    acks_late=True,
    time_limit=900,
    soft_time_limit=840,
    name="bisheng.worker.approval.file_change_tasks.purge_file_change_delete",
    **_RETRY_OPTIONS,
)
def purge_file_change_delete(
    self,
    *,
    request_id: int,
    execution_token: str,
) -> dict:
    """Continue verified, idempotent post-cutover physical cleanup."""

    return _run_in_task_tenant(
        request=self.request,
        coroutine_factory=lambda tenant_id: _purge_delete_async(
            tenant_id=tenant_id,
            request_id=int(request_id),
            execution_token=str(execution_token),
        ),
    )


@bisheng_celery.task(
    bind=True,
    acks_late=True,
    time_limit=900,
    soft_time_limit=840,
    name="bisheng.worker.approval.file_change_tasks.cleanup_file_change_mutation",
    **_RETRY_OPTIONS,
)
def cleanup_file_change_mutation(
    self,
    *,
    request_id: int,
    execution_token: str,
) -> dict:
    """Continue token-bound rename/move cleanup after the atomic view switch."""

    return _run_in_task_tenant(
        request=self.request,
        coroutine_factory=lambda tenant_id: _cleanup_mutation_async(
            tenant_id=tenant_id,
            request_id=int(request_id),
            execution_token=str(execution_token),
        ),
    )


@bisheng_celery.task(
    bind=True,
    acks_late=True,
    time_limit=900,
    soft_time_limit=840,
    name="bisheng.worker.approval.file_change_tasks.continue_file_change_compensation",
    **_RETRY_OPTIONS,
)
def continue_file_change_compensation(
    self,
    *,
    request_id: int,
    execution_token: str,
) -> dict:
    """Continue verified owner compensation for one current generation."""

    return _run_in_task_tenant(
        request=self.request,
        coroutine_factory=lambda tenant_id: _continue_compensation_async(
            tenant_id=tenant_id,
            request_id=int(request_id),
            execution_token=str(execution_token),
        ),
    )


async def _coordinate_execution_async(
    *,
    tenant_id: int,
    outbox_id: int,
    execution_token: str,
) -> dict:
    coordinator = _build_execution_coordinator()
    status = await coordinator.coordinate_outbox_execution(
        tenant_id=int(tenant_id),
        outbox_id=int(outbox_id),
        execution_token=str(execution_token),
        dispatcher=_dispatch_file_change_step,
    )
    return {"status": str(status)}


async def _watchdog_execution_async(
    *,
    tenant_id: int,
    outbox_id: int,
    execution_token: str,
    heartbeat_timeout_seconds: int,
) -> dict:
    if heartbeat_timeout_seconds <= 0:
        raise ValueError("F046 watchdog heartbeat timeout must be positive")
    coordinator = _build_execution_coordinator()
    identity = await coordinator.load_identity(
        tenant_id=int(tenant_id),
        outbox_id=int(outbox_id),
        execution_token=str(execution_token),
    )
    if identity is None:
        return {"status": "ignored"}
    failed = await coordinator.fail(
        identity=identity,
        error_summary="deferred execution watchdog timeout",
        watchdog=True,
        heartbeat_timeout_seconds=int(heartbeat_timeout_seconds),
    )
    return {"status": "failed" if failed else "running"}


async def _dispatch_file_change_step(context) -> str:
    """Enqueue evidence only; task id never acknowledges step completion."""

    execute_file_change_step.apply_async(
        kwargs={
            "request_id": int(context.request_id),
            "instance_id": int(context.instance_id),
            "outbox_id": int(context.outbox_id),
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
    tenant_id = int(kwargs["tenant_id"])
    request_id = int(kwargs["request_id"])
    instance_id = int(kwargs["instance_id"])
    outbox_id = int(kwargs["outbox_id"])
    execution_token = str(kwargs["execution_token"])
    step_code = str(kwargs["step_code"])
    coordinator = _build_execution_coordinator()
    identity = await coordinator.load_identity(
        tenant_id=tenant_id,
        outbox_id=outbox_id,
        execution_token=execution_token,
    )
    if identity is None or identity.request_id != request_id or identity.instance_id != instance_id:
        return {"status": "ignored"}
    executor = _build_mutation_executor()
    verifier = getattr(executor, "execute_and_verify_step", None)
    if verifier is None:
        raise RuntimeError("F046 owner step verifier is not available")
    status = await coordinator.acknowledge_step(
        identity=identity,
        step_code=step_code,
        verifier=verifier,
    )
    return {"status": str(status)}


async def _acknowledge_upload_pipeline_async(
    *,
    tenant_id: int,
    request_id: int,
    execution_token: str,
    file_id: int,
) -> dict:
    status = await _build_execution_coordinator().acknowledge_upload_terminal(
        tenant_id=int(tenant_id),
        request_id=int(request_id),
        execution_token=str(execution_token),
        file_id=int(file_id),
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
    handler = await build_runtime_handler(FILE_CHANGE_SCENARIO_CODE)
    request = await handler.terminal_cleanup(
        tenant_id=int(tenant_id),
        request_id=int(request_id),
        upload_id=str(upload_id),
        terminal_action=str(terminal_action),
        reason=reason,
    )
    return {"cleanup_state": str(request.cleanup_state)} if hasattr(request, "cleanup_state") else request


async def _cleanup_orphan_upload_stage_async(*, tenant_id: int, upload_id: str) -> dict:
    del tenant_id  # owner Service validates the restored tenant ContextVar
    service = await _build_upload_stage_service()
    reconciled = await service.reconcile_lifecycle(str(upload_id))
    return {"status": "reconciled" if reconciled else "ignored"}


async def _purge_delete_async(
    *,
    tenant_id: int,
    request_id: int,
    execution_token: str,
) -> dict:
    del tenant_id  # owner Service reads and validates the restored ContextVar
    purged = await _build_mutation_executor().purge_delete(
        request_id=int(request_id),
        execution_token=str(execution_token),
    )
    if not purged:
        raise RuntimeError("F046 delete purge is not verified complete")
    return {"status": "purged"}


async def _cleanup_mutation_async(
    *,
    tenant_id: int,
    request_id: int,
    execution_token: str,
) -> dict:
    del tenant_id
    completed = await _build_mutation_executor().continue_post_cutover_cleanup(
        request_id=int(request_id),
        execution_token=str(execution_token),
    )
    return {"status": "cleaned" if completed else "ignored"}


async def _continue_compensation_async(
    *,
    tenant_id: int,
    request_id: int,
    execution_token: str,
) -> dict:
    del tenant_id  # owner Service validates the restored tenant ContextVar
    executor = _build_mutation_executor()
    continue_compensation = getattr(executor, "continue_compensation", None)
    if continue_compensation is None:
        raise RuntimeError("F046 owner compensation continuation is not available")
    completed = await continue_compensation(
        request_id=int(request_id),
        execution_token=str(execution_token),
    )
    return {"status": "compensated" if completed else "ignored"}


def _build_execution_coordinator():
    from bisheng.knowledge.domain.services.knowledge_space_file_change_execution_coordinator import (
        KnowledgeSpaceFileChangeExecutionCoordinator,
    )

    return KnowledgeSpaceFileChangeExecutionCoordinator()


def _build_mutation_executor():
    from bisheng.knowledge.domain.services.knowledge_space_mutation_executor import (
        KnowledgeSpaceMutationExecutor,
    )

    return KnowledgeSpaceMutationExecutor()


async def _build_upload_stage_service():
    from bisheng.core.storage.minio.minio_manager import get_minio_storage
    from bisheng.knowledge.domain.services.knowledge_space_upload_stage_service import (
        KnowledgeSpaceUploadStageService,
    )

    async def capacity_loader_not_used(_tenant_id: int, _user_id: int):
        raise RuntimeError("capacity loading is not used by expired orphan cleanup")

    return KnowledgeSpaceUploadStageService(
        storage=await get_minio_storage(),
        capacity_loader=capacity_loader_not_used,
    )


@bisheng_celery.task(
    bind=True,
    acks_late=True,
    time_limit=900,
    soft_time_limit=840,
    name="bisheng.worker.approval.file_change_tasks.reconcile_space_file_change_approvers",
    **_RETRY_OPTIONS,
)
def reconcile_space_file_change_approvers(
    self,
    space_id: int,
    *,
    after_instance_id: int = 0,
) -> dict:
    """Permission-event entrypoint for one knowledge space."""

    return _run_in_task_tenant(
        request=self.request,
        coroutine_factory=lambda tenant_id: _reconcile_space_async(
            tenant_id=tenant_id,
            space_id=int(space_id),
            after_instance_id=int(after_instance_id),
        ),
    )


@bisheng_celery.task(
    bind=True,
    acks_late=True,
    time_limit=900,
    soft_time_limit=840,
    name="bisheng.worker.approval.file_change_tasks.reconcile_tenant_file_change_approvers",
    **_RETRY_OPTIONS,
)
def reconcile_tenant_file_change_approvers(
    self,
    *,
    after_update_time: str | None = None,
    after_request_id: int = 0,
) -> dict:
    """Process one bounded Beat reconciliation page for a tenant."""

    return _run_in_task_tenant(
        request=self.request,
        coroutine_factory=lambda tenant_id: _reconcile_tenant_async(
            tenant_id=tenant_id,
            after_update_time=after_update_time,
            after_request_id=int(after_request_id),
        ),
    )


@bisheng_celery.task(
    acks_late=True,
    time_limit=900,
    soft_time_limit=840,
    name="bisheng.worker.approval.file_change_tasks.reconcile_all_file_change_approvers",
)
def reconcile_all_file_change_approvers() -> dict:
    """Beat coordinator: enumerate tenants once and dispatch isolated pages."""

    return run_async_task(_coordinate_all_tenants_async)


@bisheng_celery.task(
    bind=True,
    acks_late=True,
    time_limit=900,
    soft_time_limit=840,
    name="bisheng.worker.approval.file_change_tasks.watchdog_tenant_file_change_executions",
    **_RETRY_OPTIONS,
)
def watchdog_tenant_file_change_executions(
    self,
    *,
    after_outbox_id: int = 0,
) -> dict:
    return _run_in_task_tenant(
        request=self.request,
        coroutine_factory=lambda tenant_id: _watchdog_tenant_page_async(
            tenant_id=tenant_id,
            after_outbox_id=int(after_outbox_id),
        ),
    )


@bisheng_celery.task(
    acks_late=True,
    time_limit=900,
    soft_time_limit=840,
    name="bisheng.worker.approval.file_change_tasks.watchdog_all_file_change_executions",
    **_RETRY_OPTIONS,
)
def watchdog_all_file_change_executions() -> dict:
    return run_async_task(_coordinate_watchdog_all_tenants_async)


@bisheng_celery.task(
    bind=True,
    acks_late=True,
    time_limit=900,
    soft_time_limit=840,
    name="bisheng.worker.approval.file_change_tasks.compensate_tenant_file_change_execution_steps",
    **_RETRY_OPTIONS,
)
def compensate_tenant_file_change_execution_steps(
    self,
    *,
    after_step_id: int = 0,
) -> dict:
    return _run_in_task_tenant(
        request=self.request,
        coroutine_factory=lambda tenant_id: _compensate_tenant_step_page_async(
            tenant_id=tenant_id,
            after_step_id=int(after_step_id),
        ),
    )


@bisheng_celery.task(
    acks_late=True,
    time_limit=900,
    soft_time_limit=840,
    name="bisheng.worker.approval.file_change_tasks.compensate_all_file_change_execution_steps",
    **_RETRY_OPTIONS,
)
def compensate_all_file_change_execution_steps() -> dict:
    return run_async_task(_coordinate_step_recovery_all_tenants_async)


@bisheng_celery.task(
    bind=True,
    acks_late=True,
    time_limit=900,
    soft_time_limit=840,
    name="bisheng.worker.approval.file_change_tasks.cleanup_tenant_file_change_residue",
    **_RETRY_OPTIONS,
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
    acks_late=True,
    time_limit=900,
    soft_time_limit=840,
    name="bisheng.worker.approval.file_change_tasks.cleanup_all_file_change_residue",
    **_RETRY_OPTIONS,
)
def cleanup_all_file_change_residue() -> dict:
    return run_async_task(_coordinate_cleanup_all_tenants_async)


async def _watchdog_tenant_page_async(*, tenant_id: int, after_outbox_id: int) -> dict:
    page = await _build_compensation_service().list_deferred_watchdog_page(
        tenant_id=int(tenant_id),
        scenario_code=FILE_CHANGE_SCENARIO_CODE,
        after_outbox_id=int(after_outbox_id),
        limit=COMPENSATION_BATCH_SIZE,
    )
    dispatched = 0
    failed = 0
    for candidate in page.items:
        try:
            watchdog_file_change_execution.apply_async(
                kwargs={
                    "outbox_id": int(candidate.outbox_id),
                    "execution_token": str(candidate.execution_token),
                },
                headers={"tenant_id": int(tenant_id)},
            )
            dispatched += 1
        except Exception:
            failed += 1
            logger.exception(
                "F046 deferred watchdog dispatch failed: tenant_id={} outbox_id={}",
                tenant_id,
                candidate.outbox_id,
            )
    if page.has_more:
        _require_advanced_id_cursor(
            current_id=int(after_outbox_id),
            next_id=int(page.next_after_id),
            cursor_name="outbox",
        )
        watchdog_tenant_file_change_executions.apply_async(
            kwargs={"after_outbox_id": int(page.next_after_id)},
            headers={"tenant_id": int(tenant_id)},
        )
    return {
        "processed": len(page.items),
        "dispatched": dispatched,
        "failed": failed,
        "has_more": bool(page.has_more),
    }


async def _compensate_tenant_step_page_async(*, tenant_id: int, after_step_id: int) -> dict:
    from bisheng.knowledge.domain.models.knowledge_space_file_change_request import (
        KnowledgeSpaceFileChangeExecutionState,
    )

    page = await _build_compensation_service().list_step_recovery_page(
        tenant_id=int(tenant_id),
        scenario_code=FILE_CHANGE_SCENARIO_CODE,
        after_step_id=int(after_step_id),
        limit=COMPENSATION_BATCH_SIZE,
    )
    dispatched = 0
    failed = 0
    seen_generations: set[tuple[int, str, str]] = set()
    for candidate in page.items:
        generation = (
            int(candidate.request_id),
            str(candidate.execution_token),
            str(candidate.execution_state),
        )
        if generation in seen_generations:
            continue
        seen_generations.add(generation)
        try:
            if candidate.execution_state == KnowledgeSpaceFileChangeExecutionState.COMPENSATING:
                continue_file_change_compensation.apply_async(
                    kwargs={
                        "request_id": int(candidate.request_id),
                        "execution_token": str(candidate.execution_token),
                    },
                    headers={"tenant_id": int(tenant_id)},
                )
            else:
                coordinate_file_change_execution.apply_async(
                    kwargs={
                        "outbox_id": int(candidate.outbox_id),
                        "execution_token": str(candidate.execution_token),
                    },
                    headers={"tenant_id": int(tenant_id)},
                )
            dispatched += 1
        except Exception:
            failed += 1
            logger.exception(
                "F046 execution recovery dispatch failed: tenant_id={} request_id={}",
                tenant_id,
                candidate.request_id,
            )
    if page.has_more:
        _require_advanced_id_cursor(
            current_id=int(after_step_id),
            next_id=int(page.next_after_id),
            cursor_name="step",
        )
        compensate_tenant_file_change_execution_steps.apply_async(
            kwargs={"after_step_id": int(page.next_after_id)},
            headers={"tenant_id": int(tenant_id)},
        )
    return {
        "processed": len(page.items),
        "dispatched": dispatched,
        "failed": failed,
        "has_more": bool(page.has_more),
    }


async def _cleanup_tenant_page_async(
    *,
    tenant_id: int,
    after_request_id: int,
    after_stage_id: int,
) -> dict:
    service = _build_compensation_service()
    page = await service.list_cleanup_page(
        tenant_id=int(tenant_id),
        scenario_code=FILE_CHANGE_SCENARIO_CODE,
        after_request_id=int(after_request_id),
        limit=COMPENSATION_BATCH_SIZE,
    )
    stage_page = await service.list_expired_orphan_stage_page(
        tenant_id=int(tenant_id),
        after_stage_id=int(after_stage_id),
        limit=COMPENSATION_BATCH_SIZE,
    )
    dispatched = 0
    failed = 0
    for candidate in page.items:
        try:
            if candidate.kind == "stage":
                cleanup_file_change_upload_stage.apply_async(
                    kwargs={
                        "request_id": int(candidate.request_id),
                        "upload_id": str(candidate.upload_id),
                        "terminal_action": str(candidate.terminal_action),
                    },
                    headers={"tenant_id": int(tenant_id)},
                )
            elif candidate.kind == "delete_purge":
                purge_file_change_delete.apply_async(
                    kwargs={
                        "request_id": int(candidate.request_id),
                        "execution_token": str(candidate.execution_token),
                    },
                    headers={"tenant_id": int(tenant_id)},
                )
            elif candidate.kind == "mutation_cleanup":
                cleanup_file_change_mutation.apply_async(
                    kwargs={
                        "request_id": int(candidate.request_id),
                        "execution_token": str(candidate.execution_token),
                    },
                    headers={"tenant_id": int(tenant_id)},
                )
            else:
                raise ValueError(f"unsupported F046 cleanup candidate: {candidate.kind}")
            dispatched += 1
        except Exception:
            failed += 1
            logger.exception(
                "F046 cleanup dispatch failed: tenant_id={} request_id={}",
                tenant_id,
                candidate.request_id,
            )
    for candidate in stage_page.items:
        try:
            cleanup_orphan_file_change_upload_stage.apply_async(
                kwargs={"upload_id": str(candidate.upload_id)},
                headers={"tenant_id": int(tenant_id)},
            )
            dispatched += 1
        except Exception:
            failed += 1
            logger.exception(
                "F046 stage lifecycle dispatch failed: tenant_id={} stage_id={}",
                tenant_id,
                candidate.stage_id,
            )
    has_more = bool(page.has_more or stage_page.has_more)
    if has_more:
        next_request_id = int(page.next_after_id)
        next_stage_id = int(stage_page.next_after_id)
        if page.has_more:
            _require_advanced_id_cursor(
                current_id=int(after_request_id),
                next_id=next_request_id,
                cursor_name="request",
            )
        if stage_page.has_more:
            _require_advanced_id_cursor(
                current_id=int(after_stage_id),
                next_id=next_stage_id,
                cursor_name="stage",
            )
        cleanup_tenant_file_change_residue.apply_async(
            kwargs={
                "after_request_id": next_request_id,
                "after_stage_id": next_stage_id,
            },
            headers={"tenant_id": int(tenant_id)},
        )
    return {
        "processed": len(page.items) + len(stage_page.items),
        "dispatched": dispatched,
        "failed": failed,
        "has_more": has_more,
    }


def _require_advanced_id_cursor(*, current_id: int, next_id: int, cursor_name: str) -> None:
    if int(next_id) <= int(current_id):
        raise RuntimeError(f"F046 {cursor_name} compensation cursor did not advance")


def _build_compensation_service():
    from bisheng.knowledge.domain.services.knowledge_space_file_change_compensation_service import (
        KnowledgeSpaceFileChangeCompensationService,
    )

    return KnowledgeSpaceFileChangeCompensationService()


def _run_in_task_tenant(*, request, coroutine_factory: Callable[[int], object]):
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
        raise ValueError("F046 reconcile worker requires a tenant_id header")
    try:
        tenant_id = int(raw_tenant_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("F046 reconcile worker tenant_id header must be a positive integer") from exc
    if tenant_id <= 0:
        raise ValueError("F046 reconcile worker tenant_id header must be a positive integer")
    return tenant_id


async def _reconcile_space_async(
    *,
    tenant_id: int,
    space_id: int,
    after_instance_id: int,
) -> dict:
    handler = await build_runtime_handler(FILE_CHANGE_SCENARIO_CODE)
    result = await handler.reconcile_space_pending_approvers(
        tenant_id=int(tenant_id),
        space_id=int(space_id),
        trigger="permission_event",
        after_instance_id=int(after_instance_id),
        limit=RECONCILE_BATCH_SIZE,
    )
    if result.get("has_more"):
        next_after_instance_id = int(result["next_after_instance_id"])
        if next_after_instance_id <= int(after_instance_id):
            raise RuntimeError("F046 space reconciliation cursor did not advance")
        reconcile_space_file_change_approvers.apply_async(
            args=[int(space_id)],
            kwargs={"after_instance_id": next_after_instance_id},
            headers={"tenant_id": int(tenant_id)},
        )
    return result


async def _reconcile_tenant_async(
    *,
    tenant_id: int,
    after_update_time: str | None,
    after_request_id: int,
) -> dict:
    handler = await build_runtime_handler(FILE_CHANGE_SCENARIO_CODE)
    result = await handler.reconcile_tenant_pending_approvers(
        tenant_id=int(tenant_id),
        trigger="beat",
        after_update_time=after_update_time,
        after_request_id=int(after_request_id),
        limit=RECONCILE_BATCH_SIZE,
    )
    if result.get("has_more"):
        next_update_time = result.get("next_after_update_time")
        next_request_id = int(result["next_after_request_id"])
        _require_advanced_tenant_cursor(
            after_update_time=after_update_time,
            after_request_id=int(after_request_id),
            next_update_time=next_update_time,
            next_request_id=next_request_id,
        )
        reconcile_tenant_file_change_approvers.apply_async(
            kwargs={
                "after_update_time": next_update_time,
                "after_request_id": next_request_id,
            },
            headers={"tenant_id": int(tenant_id)},
        )
    return result


def _require_advanced_tenant_cursor(
    *,
    after_update_time: str | None,
    after_request_id: int,
    next_update_time: str | None,
    next_request_id: int,
) -> None:
    if next_update_time is None:
        raise RuntimeError("F046 tenant reconciliation continuation has no update_time cursor")
    try:
        next_value = datetime.fromisoformat(next_update_time)
        current_value = datetime.fromisoformat(after_update_time) if after_update_time else None
    except (TypeError, ValueError) as exc:
        raise RuntimeError("F046 tenant reconciliation continuation has an invalid cursor") from exc
    if current_value is not None and (next_value, next_request_id) <= (current_value, after_request_id):
        raise RuntimeError("F046 tenant reconciliation cursor did not advance")


async def _coordinate_all_tenants_async() -> dict:
    # This is the only cross-tenant read. Business reconciliation is always
    # delegated to a task carrying an explicit tenant header.
    with bypass_tenant_filter():
        tenant_ids = await _load_active_tenant_ids()

    dispatched = 0
    failed = 0
    for tenant_id in sorted({int(value) for value in tenant_ids if int(value) > 0}):
        try:
            reconcile_tenant_file_change_approvers.apply_async(
                kwargs={"after_update_time": None, "after_request_id": 0},
                headers={"tenant_id": tenant_id},
            )
            dispatched += 1
        except Exception:
            failed += 1
            logger.exception("F046 tenant reconciliation dispatch failed: tenant_id={}", tenant_id)
    return {
        "tenant_count": len(tenant_ids),
        "dispatched": dispatched,
        "failed": failed,
    }


async def _coordinate_watchdog_all_tenants_async() -> dict:
    return await _coordinate_maintenance_all_tenants_async(
        tenant_task=watchdog_tenant_file_change_executions,
        initial_kwargs={"after_outbox_id": 0},
        operation="deferred_watchdog",
    )


async def _coordinate_step_recovery_all_tenants_async() -> dict:
    return await _coordinate_maintenance_all_tenants_async(
        tenant_task=compensate_tenant_file_change_execution_steps,
        initial_kwargs={"after_step_id": 0},
        operation="execution_recovery",
    )


async def _coordinate_cleanup_all_tenants_async() -> dict:
    return await _coordinate_maintenance_all_tenants_async(
        tenant_task=cleanup_tenant_file_change_residue,
        initial_kwargs={"after_request_id": 0, "after_stage_id": 0},
        operation="cleanup",
    )


async def _coordinate_maintenance_all_tenants_async(*, tenant_task, initial_kwargs: dict, operation: str) -> dict:
    # The bypass is restricted to tenant enumeration. Every business page is
    # delegated with a positive tenant header and restores ContextVar itself.
    with bypass_tenant_filter():
        tenant_ids = await _load_active_tenant_ids()

    normalized_tenant_ids = sorted({int(value) for value in tenant_ids if int(value) > 0})
    dispatched = 0
    failed = 0
    for tenant_id in normalized_tenant_ids:
        try:
            tenant_task.apply_async(
                kwargs=dict(initial_kwargs),
                headers={"tenant_id": int(tenant_id)},
            )
            dispatched += 1
        except Exception:
            failed += 1
            logger.exception(
                "F046 maintenance tenant dispatch failed: operation={} tenant_id={}",
                operation,
                tenant_id,
            )
    return {
        "tenant_count": len(normalized_tenant_ids),
        "dispatched": dispatched,
        "failed": failed,
    }


async def _load_active_tenant_ids() -> list[int]:
    from bisheng.common.services.config_service import settings

    if not settings.multi_tenant.enabled:
        return [DEFAULT_TENANT_ID]
    from bisheng.database.models.tenant import TenantDao

    return sorted(await TenantDao.aget_active_ids())
