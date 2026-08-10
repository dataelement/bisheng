from __future__ import annotations

from loguru import logger

from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository
from bisheng.approval.domain.services.approval_outbox_service import ApprovalOutboxService
from bisheng.approval.domain.services.approval_runtime_handler_factory import build_runtime_handler
from bisheng.approval.domain.services.resource_user_invite_scenario_handler import (
    ApprovalInviteRetryableExecutionError,
)
from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery


@bisheng_celery.task(
    acks_late=True,
    autoretry_for=(ApprovalInviteRetryableExecutionError,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 8},
    time_limit=900,
    soft_time_limit=840,
    name="bisheng.worker.approval.tasks.execute_approval_outbox",
)
def execute_approval_outbox(outbox_id: int) -> bool:
    return run_async_task(lambda: _execute_approval_outbox_async(outbox_id))


@bisheng_celery.task(
    acks_late=True,
    autoretry_for=(ApprovalInviteRetryableExecutionError,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 8},
    time_limit=900,
    soft_time_limit=840,
    name="bisheng.worker.approval.tasks.retry_approval_outbox",
)
def retry_approval_outbox(outbox_id: int) -> bool:
    return run_async_task(lambda: _retry_approval_outbox_async(outbox_id))


async def _execute_approval_outbox_async(outbox_id: int) -> bool:
    outbox = await ApprovalInstanceRepository.get_outbox(outbox_id)
    if outbox is None:
        raise ValueError(f"approval outbox not found: {outbox_id}")
    from bisheng.approval.domain.models.approval_instance import ApprovalOutboxStatus

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
    except ApprovalInviteRetryableExecutionError:
        raise
    except Exception as exc:
        logger.exception("approval outbox task setup failed: outbox_id={}", outbox_id)
        await _record_outbox_task_failure(outbox, str(exc))
        return False


async def _retry_approval_outbox_async(outbox_id: int) -> bool:
    outbox = await ApprovalInstanceRepository.get_outbox(outbox_id)
    if outbox is None:
        raise ValueError(f"approval outbox not found: {outbox_id}")
    from bisheng.approval.domain.models.approval_instance import ApprovalOutboxStatus

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
    except ApprovalInviteRetryableExecutionError:
        raise
    except Exception as exc:
        logger.exception("approval outbox retry task setup failed: outbox_id={}", outbox_id)
        await _record_outbox_task_failure(outbox, str(exc))
        return False


async def _record_outbox_task_failure(outbox, error_summary: str) -> None:
    """Mark outbox as failed and create an exception record so the admin UI can show it."""
    try:
        await ApprovalInstanceRepository.record_outbox_setup_failure(
            outbox_id=outbox.id,
            error_summary=error_summary,
        )
    except Exception:
        logger.exception("failed to record outbox task failure: outbox_id={}", outbox.id)


def _build_outbox_executor(*, handler, instance_id: int):
    async def _executor(outbox):
        try:
            await handler.on_approved(instance_id, outbox.payload_snapshot)
            return True, None
        except ApprovalInviteRetryableExecutionError:
            raise
        except Exception as exc:
            logger.exception("approval outbox execution failed: outbox_id={}", outbox.id)
            return False, str(exc)

    return _executor
