"""Celery registration and bounded active-stream scheduling for DSH."""

from datetime import UTC, datetime

from celery.signals import worker_shutting_down

from bisheng.dsh.domain.services.profile import profile_scope
from bisheng.dsh.domain.services.usage_dispatch import UsageDispatcher
from bisheng.worker.dsh.content_safety import register_content_safety_tasks
from bisheng.worker.dsh.model_audit import register_model_audit_tasks
from bisheng.worker.dsh.model_audit_tree import register_audit_tree_tasks
from bisheng.worker.dsh.operations import register_operation_tasks
from bisheng.worker.dsh.usage import register_usage_tasks


def register_dsh_tasks(app):
    register_model_audit_tasks(app)
    register_audit_tree_tasks(app)
    register_content_safety_tasks(app)
    from bisheng.dsh.operations_runtime import (
        active_tenant_ids,
        administration_worker_runtime,
        projection_worker_runtime,
    )
    from bisheng.worker._asyncio_utils import run_async_task

    project = register_usage_tasks(app, projection_worker_runtime)
    register_operation_tasks(
        app, administration_worker_runtime, active_tenant_ids, lambda: datetime.now(UTC).replace(tzinfo=None)
    )

    @app.task(bind=True, name="dsh.inspect_usage")
    def inspect_usage(task, tenant_id: int, user_id: int, cursor: int = 0):
        # Celery request state is thread-local; capture it before the async bridge.
        headers = dict(task.request.headers or {})

        async def execute():
            if type(headers.get("tenant_id")) is not int or headers["tenant_id"] != tenant_id:
                raise ValueError("DSH inspection requires a matching trusted tenant header")
            with profile_scope(tenant_id):
                async with projection_worker_runtime() as service:
                    _, changed = await service.inspect_running(
                        tenant_id, user_id, now=datetime.now(UTC), timeout_seconds=3600, cursor=cursor
                    )
                    await service.cleanup_batch(tenant_id, user_id)
                    return changed

        return run_async_task(execute)

    @app.task(name="dsh.dispatch_usage", ignore_result=True)
    def dispatch_usage():
        async def execute():
            async with projection_worker_runtime() as service:
                return await UsageDispatcher(service).dispatch()

        return run_async_task(execute)

    @app.task(name="dsh.scan_usage", ignore_result=True)
    def scan_usage(cursor: int = 0, inspect_requests: bool = False, owner: str | None = None):
        async def execute():
            # Keep the old task signature for already queued messages; never fan out or recurse.
            async with projection_worker_runtime() as service:
                return await UsageDispatcher(service).repair()

        return run_async_task(execute)

    return {"project": project, "inspect": inspect_usage, "scan": scan_usage, "dispatch": dispatch_usage}


def close_dsh_worker_runtime(**kwargs):
    from bisheng.dsh.operations_runtime import close_operations_worker_runtime
    from bisheng.worker._asyncio_utils import run_async_task

    run_async_task(close_operations_worker_runtime)


worker_shutting_down.connect(close_dsh_worker_runtime)
