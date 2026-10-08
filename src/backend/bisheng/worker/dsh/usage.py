"""Trusted tenant-header entry points; application startup owns Celery registration."""

from bisheng.dsh.domain.services.profile import profile_scope
from bisheng.dsh.domain.services.projection import DshProjectionService


async def project_user(headers: dict, tenant_id: int, user_id: int, service: DshProjectionService):
    if (
        type(tenant_id) is not int
        or tenant_id < 1
        or type(headers.get("tenant_id")) is not int
        or headers.get("tenant_id") != tenant_id
    ):
        raise ValueError("Trusted task tenant header must match payload")
    with profile_scope(tenant_id):
        return await service.project_batch(tenant_id, user_id)


def register_usage_tasks(app, runtime_factory):
    """Runtime factory is configured in every worker role; no filesystem or process-local ledger."""

    @app.task(bind=True, name="dsh.project_usage")
    def project_usage(task, tenant_id: int, user_id: int):
        # Celery request state is thread-local; capture it before the async bridge.
        headers = dict(task.request.headers or {})

        async def execute():
            async with runtime_factory() as service:
                if type(headers.get("tenant_id")) is not int or headers["tenant_id"] != tenant_id:
                    raise ValueError("Trusted task tenant header must match payload")
                with profile_scope(tenant_id):
                    count, more = await service.drain_user(tenant_id, user_id)
                if more:
                    project_usage.apply_async(args=[tenant_id, user_id], headers={"tenant_id": tenant_id})
                return count

        from bisheng.worker._asyncio_utils import run_async_task

        return run_async_task(execute)

    return project_usage
