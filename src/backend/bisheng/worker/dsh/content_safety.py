"""Bounded safety projection jobs, independent of model execution and tenant mode."""

from contextlib import contextmanager

from loguru import logger


def register_content_safety_tasks(app):
    from bisheng.dsh.domain.repositories.model_audit_queries import DshModelAuditQueryRepository
    from bisheng.dsh.domain.services.model_audit_projection import project_audit_groups
    from bisheng.dsh.domain.services.model_audit_queries import DshModelAuditQueryService
    from bisheng.dsh.domain.services.model_audit_tree import DshAuditTreeProjectionService
    from bisheng.dsh.domain.services.profile import profile_scope
    from bisheng.dsh.infrastructure.model_audit_blocking import run_audit_blocking
    from bisheng.worker._asyncio_utils import run_async_task

    @contextmanager
    def scope():
        from bisheng.dsh.operations_runtime import repository_scope

        with repository_scope(DshModelAuditQueryRepository) as repository:
            yield repository

    @app.task(bind=True, name="dsh.project_content_safety")
    def project(task, tenant_id, cursor="", owner=None):
        # Capture the Celery request before crossing into the async loop thread.
        headers = dict(task.request.headers or {})
        if (
            type(tenant_id) is not int
            or not 1 <= tenant_id <= 9223372036854775807
            or type(headers.get("tenant_id")) is not int
            or headers["tenant_id"] != tenant_id
        ):
            raise ValueError("Safety projection requires matching trusted tenant header")
        if not isinstance(cursor, str) or len(cursor) > 36:
            raise ValueError("Invalid safety projection cursor")

        async def execute():
            with profile_scope(tenant_id):
                queries = DshModelAuditQueryService(None, scope)
                tree = DshAuditTreeProjectionService(scope)
                try:
                    position, _changed = await project_audit_groups(queries, tenant_id, cursor)
                    if position:
                        project.apply_async(args=[tenant_id, position, owner], headers={"tenant_id": tenant_id})
                        return "GROUPS"
                    result = await tree.step(tenant_id, owner=owner)
                except Exception as error:
                    # Facts remain committed; a later dirty scan can retry the disposable projection.
                    logger.warning("DSH content safety projection failed ({})", type(error).__name__)
                    await tree.failed(tenant_id, owner=owner)
                    raise
                if result["has_more"]:
                    project.apply_async(args=[tenant_id, "", result.get("owner")], headers={"tenant_id": tenant_id})
                return result["status"]

        return run_async_task(execute)

    @app.task(name="dsh.scan_content_safety")
    def scan(cursor=0):
        if type(cursor) is not int or not 0 <= cursor <= 9223372036854775807:
            raise ValueError("Invalid safety tenant cursor")

        async def execute():
            def read():
                with scope() as repository:
                    return repository.tree_pending_tenants(cursor=cursor, include_group_pending=True)

            tenants = await run_audit_blocking(read)
            for tenant in tenants:
                with profile_scope(tenant):
                    project.apply_async(args=[tenant], headers={"tenant_id": tenant})
            if len(tenants) == 100:
                scan.apply_async(args=[tenants[-1]])
            return len(tenants)

        return run_async_task(execute)

    return project, scan
