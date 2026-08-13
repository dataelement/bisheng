from __future__ import annotations

from loguru import logger

from bisheng.approval.domain.models.approval_instance import ApprovalOutboxStatus
from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository
from bisheng.approval.domain.services.approval_outbox_service import ApprovalOutboxService
from bisheng.approval.domain.services.approval_runtime_handler_factory import build_runtime_handler
from bisheng.core.context.tenant import current_tenant_id, get_current_tenant_id, set_current_tenant_id
from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery


@bisheng_celery.task(
    bind=True,
    acks_late=True,
    time_limit=900,
    soft_time_limit=840,
    name="bisheng.worker.approval.tasks.execute_approval_outbox",
)
def execute_approval_outbox(self, outbox_id: int) -> bool:
    return _run_in_task_tenant(
        request=self.request,
        coroutine_factory=lambda: _execute_approval_outbox_async(outbox_id),
    )


@bisheng_celery.task(
    bind=True,
    acks_late=True,
    time_limit=900,
    soft_time_limit=840,
    name="bisheng.worker.approval.tasks.retry_approval_outbox",
)
def retry_approval_outbox(self, outbox_id: int) -> bool:
    return _run_in_task_tenant(
        request=self.request,
        coroutine_factory=lambda: _retry_approval_outbox_async(outbox_id),
    )


def _run_in_task_tenant(*, request, coroutine_factory) -> bool:
    tenant_id = _require_tenant_id_header(request)
    tenant_token = set_current_tenant_id(tenant_id)
    try:
        return run_async_task(coroutine_factory)
    finally:
        current_tenant_id.reset(tenant_token)


def _require_tenant_id_header(request) -> int:
    headers = getattr(request, "headers", None) or {}
    raw_tenant_id = headers.get("tenant_id")
    if raw_tenant_id is None or isinstance(raw_tenant_id, bool):
        raise ValueError("approval worker requires a tenant_id header")
    try:
        tenant_id = int(raw_tenant_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("approval worker tenant_id header must be a positive integer") from exc
    if tenant_id <= 0:
        raise ValueError("approval worker tenant_id header must be a positive integer")
    return tenant_id


async def _execute_approval_outbox_async(outbox_id: int) -> bool:
    outbox = await ApprovalInstanceRepository.get_outbox(outbox_id)
    if outbox is None:
        raise ValueError(f"approval outbox not found: {outbox_id}")
    _require_outbox_tenant(outbox)
    if outbox.status == ApprovalOutboxStatus.SUCCESS:
        await ApprovalInstanceRepository.finalize_outbox_success(outbox_id=outbox_id)
        return True
    try:
        instance = await ApprovalInstanceRepository.get_instance(outbox.instance_id)
        if instance is None:
            raise ValueError(f"approval instance not found: {outbox.instance_id}")
        handler = await build_runtime_handler(outbox.handler_key)
        service = ApprovalOutboxService(instance_repository=ApprovalInstanceRepository)
        return await service.execute_outbox(
            outbox_id=outbox_id,
            executor=_build_outbox_executor(handler=handler, instance_id=instance.id),
        )
    except Exception as exc:
        logger.exception("approval outbox task setup failed: outbox_id={}", outbox_id)
        await _record_outbox_task_failure(outbox, str(exc))
        return False


async def _retry_approval_outbox_async(outbox_id: int) -> bool:
    outbox = await ApprovalInstanceRepository.get_outbox(outbox_id)
    if outbox is None:
        raise ValueError(f"approval outbox not found: {outbox_id}")
    _require_outbox_tenant(outbox)
    if outbox.status == ApprovalOutboxStatus.SUCCESS:
        await ApprovalInstanceRepository.finalize_outbox_success(outbox_id=outbox_id)
        return True
    try:
        instance = await ApprovalInstanceRepository.get_instance(outbox.instance_id)
        if instance is None:
            raise ValueError(f"approval instance not found: {outbox.instance_id}")
        handler = await build_runtime_handler(outbox.handler_key)
        service = ApprovalOutboxService(instance_repository=ApprovalInstanceRepository)
        return await service.retry_outbox(
            outbox_id=outbox_id,
            executor=_build_outbox_executor(handler=handler, instance_id=instance.id),
        )
    except Exception as exc:
        logger.exception("approval outbox retry task setup failed: outbox_id={}", outbox_id)
        await _record_outbox_task_failure(outbox, str(exc))
        return False


async def _record_outbox_task_failure(outbox, error_summary: str) -> None:
    """Persist setup failure so the released scenarios remain retryable."""

    try:
        await ApprovalInstanceRepository.record_outbox_setup_failure(
            outbox_id=outbox.id,
            error_summary=error_summary,
        )
    except Exception:
        logger.exception("failed to record outbox task failure: outbox_id={}", outbox.id)


def _require_outbox_tenant(outbox) -> None:
    tenant_id = get_current_tenant_id()
    if tenant_id is None or int(outbox.tenant_id) != int(tenant_id):
        raise ValueError("approval outbox tenant does not match the worker tenant header")


def _build_outbox_executor(*, handler, instance_id: int):
    async def _executor(outbox):
        try:
            await handler.on_approved(instance_id, outbox.payload_snapshot)
            return True, None
        except Exception as exc:
            logger.exception("approval outbox execution failed: outbox_id={}", outbox.id)
            return False, str(exc)

    return _executor
