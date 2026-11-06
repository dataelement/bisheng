"""Tenant headers are restored by worker.tenant_context; source read scopes remain explicit."""

from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery


@bisheng_celery.task(name="runtime_audit_export", acks_late=True, reject_on_worker_lost=True)
def runtime_audit_export(job_id, tenant_id):
    from bisheng.app_governance.domain.services.runtime_audit_export_service import RuntimeAuditExportService
    from bisheng.core.context.tenant import tenant_execution_scope

    with tenant_execution_scope(tenant_id):
        return run_async_task(lambda: RuntimeAuditExportService().run(job_id, tenant_id))


@bisheng_celery.task(name="runtime_audit_reconcile")
def runtime_audit_reconcile():
    async def reconcile():
        from bisheng.app_governance.domain.repositories.runtime_audit_export_repository import (
            RuntimeAuditExportRepository,
        )

        repository = RuntimeAuditExportRepository()
        for job in await repository.recoverable():
            runtime_audit_export.apply_async(args=[job.id, job.tenant_id], headers={"tenant_id": job.tenant_id})

        from datetime import datetime

        from bisheng.app_governance.domain.services.runtime_audit_storage import RuntimeAuditStorage

        for job in await repository.gc_candidates():
            # Fence terminal state first. Existing read sessions reauthorize per chunk.
            if job.lease_until and job.lease_until > datetime.utcnow():
                continue
            await repository.terminate(job.tenant_id, job.id, "failed" if job.status == "failed" else "expired")
            await RuntimeAuditStorage().remove_prefix(f"runtime-audit/{job.tenant_id}/{job.id}/")
            await repository.mark_gc_complete(job.tenant_id, job.id)
        await repository.clear_snapshots()

    return run_async_task(reconcile)
