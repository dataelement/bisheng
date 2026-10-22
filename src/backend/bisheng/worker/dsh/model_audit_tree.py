"""Independent tree jobs, including terminal histories and tenants currently in OFF mode."""

from contextlib import contextmanager

from loguru import logger


def register_audit_tree_tasks(app):
    from bisheng.worker._asyncio_utils import run_async_task

    @app.task(bind=True, name="dsh.prepare_audit_tree")
    def prepare(task, tenant_id, owner=None):
        headers = dict(task.request.headers or {})
        if (
            type(tenant_id) is not int
            or tenant_id < 1
            or type(headers.get("tenant_id")) is not int
            or headers["tenant_id"] != tenant_id
        ):
            raise ValueError("Audit tree task requires matching trusted tenant header")

        async def execute():
            from bisheng.dsh.domain.repositories.model_audit_queries import DshModelAuditQueryRepository
            from bisheng.dsh.domain.services.model_audit_tree import DshAuditTreeProjectionService
            from bisheng.dsh.operations_runtime import repository_scope

            @contextmanager
            def scope():
                with repository_scope(DshModelAuditQueryRepository) as repo:
                    yield repo

            service = DshAuditTreeProjectionService(scope)
            try:
                result = await service.step(tenant_id, owner=owner)
            except Exception:
                # Disposable navigation must never roll back existing audit facts or billing.
                logger.exception("DSH audit tree background step failed")
                await service.failed(tenant_id, owner=owner)
                raise
            if result["has_more"]:
                prepare.apply_async(args=[tenant_id, result.get("owner")], headers={"tenant_id": tenant_id})
            return result["status"]

        return run_async_task(execute)

    @app.task(name="dsh.scan_audit_trees")
    def scan(cursor=0):
        async def execute():
            from bisheng.dsh.domain.repositories.model_audit_queries import DshModelAuditQueryRepository
            from bisheng.dsh.infrastructure.model_audit_blocking import run_audit_blocking
            from bisheng.dsh.operations_runtime import repository_scope

            def read():
                with repository_scope(DshModelAuditQueryRepository) as repo:
                    return repo.tree_pending_tenants(cursor=cursor)

            ids = await run_audit_blocking(read)
            for tenant in ids:
                prepare.apply_async(args=[tenant], headers={"tenant_id": tenant})
            if len(ids) == 100:
                scan.apply_async(args=[ids[-1]])
            return len(ids)

        return run_async_task(execute)

    return prepare, scan
