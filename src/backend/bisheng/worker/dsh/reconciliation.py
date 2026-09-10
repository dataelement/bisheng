"""Trusted worker entry point for durable UNKNOWN reconciliation operations."""

from bisheng.dsh.domain.services.profile import profile_scope


async def resume_operation(headers: dict, tenant_id: int, operation_id: str, service):
    if (
        type(tenant_id) is not int
        or tenant_id < 1
        or type(headers.get("tenant_id")) is not int
        or headers["tenant_id"] != tenant_id
    ):
        raise ValueError("Trusted task tenant header must match payload")
    with profile_scope(tenant_id):
        return await service.resume(operation_id)


def register_reconciliation_tasks(app, runtime_factory):
    @app.task(bind=True, name="dsh.reconcile_usage")
    def reconcile_usage(task, tenant_id: int, operation_id: str):
        # Celery request state is thread-local; capture it before the async bridge.
        headers = dict(task.request.headers or {})

        async def execute():
            async with runtime_factory() as runtime:
                return await resume_operation(headers, tenant_id, operation_id, runtime.reconciliation)

        from bisheng.worker._asyncio_utils import run_async_task

        return run_async_task(execute)

    return reconcile_usage
