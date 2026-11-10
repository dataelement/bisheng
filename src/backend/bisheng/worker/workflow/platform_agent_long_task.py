"""只由隔离 Mock 环境显式装配的长任务补偿。"""

from loguru import logger

from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.workflow.platform_agent_interaction import redeliver_interaction_resume


def register_long_task_reconcile(celery_app, service_factory, *, tenant_ids=(), resume_task=None, long_resume_task=None):
    if any(type(tenant_id) is not int or tenant_id <= 0 for tenant_id in tenant_ids):
        raise ValueError("invalid isolated tenant")

    @celery_app.task(name="kunlian.platform_agent_long_task_reconcile", shared=False)
    def reconcile(execution_id=None, key=None, *, cursor=None):
        headers = getattr(getattr(reconcile, "request", None), "headers", None) or {}
        tenant_id = headers.get("tenant_id")
        if type(tenant_id) is not int or tenant_id <= 0 or (execution_id is None) != (key is None):
            return None
        service = service_factory()
        if service.config.mode != "mock":
            return None
        interaction_recovery = service.enable_long_tasks and service.enable_interactions
        redeliver = interaction_recovery and resume_task is not None
        resume_recovery = getattr(service, "long_task_resume_available", False)
        resume_redeliver = resume_recovery and long_resume_task is not None

        async def reconcile_call(reference, call_key):
            if redeliver:
                redeliver_interaction_resume(service.repository, resume_task, tenant_id, reference, call_key)
            await service.reconcile_long(tenant_id, reference, call_key)
            if resume_redeliver:
                dispatch = service.repository.claim_long_task_resume_redelivery(reference, call_key, tenant_id)
                if dispatch is not None:
                    try:
                        long_resume_task.apply_async(args=[reference, call_key, dispatch], headers={"tenant_id": tenant_id})
                    except Exception as exc:
                        logger.warning("平台 Agent 长任务恢复待补投, error_type={}", type(exc).__name__)

        async def run():
            with tenant_execution_scope(tenant_id):
                if execution_id is not None:
                    await reconcile_call(execution_id, key)
                    return None
                due, next_cursor = service.repository.due_long_calls(
                    tenant_id,
                    cursor,
                    interaction_recovery=interaction_recovery,
                    redeliver=redeliver,
                    resume_recovery=resume_recovery,
                    resume_redeliver=resume_redeliver,
                )
                for reference, call_key in due:
                    try:
                        await reconcile_call(reference, call_key)
                    except Exception as exc:
                        logger.warning("平台 Agent 单项补偿待重试, error_type={}", type(exc).__name__)
                return next_cursor

        next_cursor = run_async_task(run)
        if next_cursor is not None:
            reconcile.apply_async(kwargs={"cursor": next_cursor}, headers={"tenant_id": tenant_id})
        return next_cursor

    def wake(tenant_id, execution_id, key=None):
        if key is None:
            reconcile.apply_async(headers={"tenant_id": tenant_id})
        else:
            reconcile.apply_async(args=[execution_id, key], headers={"tenant_id": tenant_id})

    for tenant_id in set(tenant_ids):
        celery_app.add_periodic_task(
            1.0, reconcile.s().set(headers={"tenant_id": tenant_id}), name=f"f124-mock-reconcile-{tenant_id}"
        )

    return reconcile, wake
