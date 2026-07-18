from __future__ import annotations

import logging

from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository
from bisheng.approval.domain.services.approval_outbox_service import ApprovalOutboxService
from bisheng.approval.domain.services.approval_runtime_handler_factory import build_runtime_handler
from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery

logger = logging.getLogger(__name__)


@bisheng_celery.task(
    acks_late=True,
    time_limit=900,
    soft_time_limit=840,
    name='bisheng.worker.approval.tasks.execute_approval_outbox',
)
def execute_approval_outbox(outbox_id: int) -> bool:
    return run_async_task(lambda: _execute_approval_outbox_async(outbox_id))


@bisheng_celery.task(
    acks_late=True,
    time_limit=900,
    soft_time_limit=840,
    name='bisheng.worker.approval.tasks.retry_approval_outbox',
)
def retry_approval_outbox(outbox_id: int) -> bool:
    return run_async_task(lambda: _retry_approval_outbox_async(outbox_id))


async def _execute_approval_outbox_async(outbox_id: int) -> bool:
    outbox = await ApprovalInstanceRepository.get_outbox(outbox_id)
    if outbox is None:
        raise ValueError(f'approval outbox not found: {outbox_id}')
    try:
        instance = await ApprovalInstanceRepository.get_instance(outbox.instance_id)
        if instance is None:
            raise ValueError(f'approval instance not found: {outbox.instance_id}')
        handler = await build_runtime_handler(outbox.handler_key)
        service = ApprovalOutboxService(instance_repository=ApprovalInstanceRepository)
        return await service.execute_outbox(
            outbox_id=outbox_id,
            executor=_build_outbox_executor(handler=handler, instance_id=instance.id),
        )
    except Exception as exc:
        logger.exception('approval outbox task setup failed: outbox_id=%s', outbox_id)
        await _record_outbox_task_failure(outbox, str(exc))
        return False


async def _retry_approval_outbox_async(outbox_id: int) -> bool:
    outbox = await ApprovalInstanceRepository.get_outbox(outbox_id)
    if outbox is None:
        raise ValueError(f'approval outbox not found: {outbox_id}')
    try:
        instance = await ApprovalInstanceRepository.get_instance(outbox.instance_id)
        if instance is None:
            raise ValueError(f'approval instance not found: {outbox.instance_id}')
        handler = await build_runtime_handler(outbox.handler_key)
        service = ApprovalOutboxService(instance_repository=ApprovalInstanceRepository)
        return await service.retry_outbox(
            outbox_id=outbox_id,
            executor=_build_outbox_executor(handler=handler, instance_id=instance.id),
        )
    except Exception as exc:
        logger.exception('approval outbox retry task setup failed: outbox_id=%s', outbox_id)
        await _record_outbox_task_failure(outbox, str(exc))
        return False


async def _record_outbox_task_failure(outbox, error_summary: str) -> None:
    """Mark outbox as failed and create an exception record so the admin UI can show it."""
    from bisheng.approval.domain.models.approval_instance import (
        ApprovalException,
        ApprovalExceptionType,
        ApprovalInstanceStatus,
        ApprovalOutboxStatus,
    )
    try:
        outbox.status = ApprovalOutboxStatus.FAILED
        outbox.retry_count += 1
        outbox.error_summary = error_summary
        await ApprovalInstanceRepository.update_outbox(outbox)

        instance = await ApprovalInstanceRepository.get_instance(outbox.instance_id)
        if instance is None or instance.status in (
            ApprovalInstanceStatus.EXECUTED,
            ApprovalInstanceStatus.CANCELLED,
            ApprovalInstanceStatus.REJECTED,
            ApprovalInstanceStatus.WITHDRAWN,
        ):
            return

        instance.status = ApprovalInstanceStatus.EXECUTE_FAILED
        await ApprovalInstanceRepository.update_instance(instance)
        await ApprovalInstanceRepository.create_exception(
            ApprovalException(
                tenant_id=instance.tenant_id,
                instance_id=instance.id,
                exception_type=ApprovalExceptionType.EXECUTE_FAILED,
                detail={'error_summary': error_summary},
            )
        )
    except Exception:
        logger.exception('failed to record outbox task failure: outbox_id=%s', outbox.id)


def _build_outbox_executor(*, handler, instance_id: int):
    async def _executor(outbox):
        try:
            await handler.on_approved(instance_id, outbox.payload_snapshot)
            return True, None
        except Exception as exc:  # noqa: BLE001
            logger.exception('approval outbox execution failed: outbox_id=%s', outbox.id)
            return False, str(exc)

    return _executor
