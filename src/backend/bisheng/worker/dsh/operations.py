"""Trusted per-tenant dispatch from durable SQL intent, never caller action names."""

from bisheng.common.errcode.dsh import DshOperationConflictError
from bisheng.dsh.domain.services.profile import profile_scope


async def dispatch_operation(headers: dict, tenant_id: int, operation_id: str, runtime):
    if (
        type(tenant_id) is not int
        or tenant_id < 1
        or type(headers.get("tenant_id")) is not int
        or headers["tenant_id"] != tenant_id
    ):
        raise ValueError("Trusted task tenant header must match payload")
    with profile_scope(tenant_id):
        with runtime.repository_scope() as repository:
            operation = repository.get(operation_id)
            if operation is None:
                raise DshOperationConflictError()
            action = operation.action
        service_name = {
            "UPDATE_POLICY": "policy",
            "RECONCILE_USAGE": "reconciliation",
            "REVOKE": "admin",
            "REASSIGN": "admin",
            "SYNC_PROFILE": "profiles",
        }.get(action)
        if service_name is None:
            raise DshOperationConflictError()
        return await getattr(runtime, service_name).resume(operation_id)


def register_operation_tasks(app, runtime_factory, tenant_ids, now):
    @app.task(bind=True, name="dsh.resume_operation")
    def resume_operation(task, tenant_id: int, operation_id: str):
        # Celery request state is thread-local; capture it before the async bridge.
        headers = dict(task.request.headers or {})

        async def execute():
            async with runtime_factory() as runtime:
                return await dispatch_operation(headers, tenant_id, operation_id, runtime)

        from bisheng.worker._asyncio_utils import run_async_task

        return run_async_task(execute)

    @app.task(name="dsh.scan_operations")
    def scan_operations():
        async def execute():
            async with runtime_factory() as runtime:
                for tenant_id in await tenant_ids():
                    with profile_scope(tenant_id):
                        with runtime.repository_scope() as repository:
                            ids = [row.operation_id for row in repository.due(now=now(), limit=100)]
                        for operation_id in ids:
                            resume_operation.apply_async(
                                args=[tenant_id, operation_id], headers={"tenant_id": tenant_id}
                            )

        from bisheng.worker._asyncio_utils import run_async_task

        return run_async_task(execute)

    return resume_operation, scan_operations
