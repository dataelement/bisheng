"""Bounded historical audit convergence, independent of current tenant mode."""

from datetime import UTC, datetime


def register_model_audit_tasks(app):
    from bisheng.worker._asyncio_utils import run_async_task

    @app.task(bind=True, name="dsh.inspect_model_audit")
    def inspect(task, tenant_id: int, cursor=None):
        headers = dict(task.request.headers or {})
        if (
            type(tenant_id) is not int
            or type(headers.get("tenant_id")) is not int
            or headers["tenant_id"] != tenant_id
            or tenant_id < 1
        ):
            raise ValueError("Audit task requires matching trusted tenant header")

        async def execute():
            from bisheng.dsh.audit_admin_runtime import build_audit_administration
            from bisheng.dsh.domain.services.model_audit_states import DshModelAuditStateService
            from bisheng.dsh.infrastructure.model_audit_activity import RedisAuditActivity
            from bisheng.dsh.operations_runtime import operations_worker_runtime

            async with operations_worker_runtime() as runtime:
                service = DshModelAuditStateService(
                    build_audit_administration(runtime.settings).queries,
                    RedisAuditActivity(runtime.quota.redis, interval=10, maximum=1, observation_window=300),
                    window=runtime.settings.audit_observation_window_seconds,
                    now=lambda: datetime.now(UTC),
                )
                next_cursor, changed = await service.inspect(tenant_id, cursor)
                if next_cursor:
                    inspect.apply_async(args=[tenant_id, next_cursor], headers={"tenant_id": tenant_id})
                return changed

        return run_async_task(execute)

    @app.task(name="dsh.scan_model_audit")
    def scan(cursor=None):
        async def execute():
            import asyncio

            from bisheng.dsh.domain.repositories.model_audit_queries import DshModelAuditQueryRepository
            from bisheng.dsh.operations_runtime import repository_scope

            def tenants():
                with repository_scope(DshModelAuditQueryRepository) as repository:
                    return repository.pending_tenants(repository.session, cursor=cursor)

            ids = await asyncio.to_thread(tenants)
            for tenant_id in ids:
                inspect.apply_async(args=[tenant_id], headers={"tenant_id": tenant_id})
            if len(ids) == 100:
                scan.apply_async(args=[ids[-1]])
            return len(ids)

        return run_async_task(execute)

    return inspect, scan
