"""Formal task module; load with Celery include in API and worker composition.

Queue messages contain only session/interaction references and tenant headers.
"""

from asyncio import to_thread

from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery
from bisheng.worker.workflow.kunlian_workflow_run import execute_run
from bisheng.workflow.application.kunlian_runtime import get_kunlian_runtime_service
from bisheng.workflow.domain.schemas.kunlian_registration import RegistrationScope


@bisheng_celery.task(name="kunlian.formal_workflow_run", shared=False)
def run(session_id, interaction_id=None):
    headers = getattr(run.request, "headers", None) or {}
    tenant_id = headers.get("tenant_id")
    if type(tenant_id) is not int or tenant_id <= 0:
        raise ValueError("Missing trusted tenant header")

    async def execute():
        service = await get_kunlian_runtime_service()
        await execute_run(service, tenant_id, session_id, interaction_id)

    run_async_task(execute)


async def reconcile_batch(service, after=None, *, limit=100):
    """One bounded page; no authorization is inferred from recovery discovery."""
    references, cursor = await to_thread(service.repository.formal_recovery_page, after, limit)
    grouped = {}
    for tenant_id, integration_id, session_id in references:
        grouped.setdefault((tenant_id, integration_id), []).append(session_id)
    for (tenant_id, integration_id), session_ids in grouped.items():
        pending = await to_thread(
            service.repository.reconcile,
            RegistrationScope(tenant_id, integration_id, 0),
            limit,
            include_resumes=True,
            session_ids=session_ids,
        )
        for session_id, interaction_id in pending:
            # execute_run revalidates original Key + current user before claiming.
            await service.deliver(tenant_id, session_id, interaction_id)
    return cursor


async def cleanup_batch(service, after=None, *, limit=100):
    """Scrub one bounded page without credential resolution or execution dispatch."""
    references, cursor = await to_thread(service.repository.formal_cleanup_page, after, limit)
    for tenant_id, connection_id, session_id in references:
        await to_thread(service.repository.cleanup_formal_expired, tenant_id, connection_id, session_id)
    return cursor


@bisheng_celery.task(name="kunlian.formal_workflow_cleanup", shared=False)
def cleanup(after=None):
    async def execute():
        return await cleanup_batch(await get_kunlian_runtime_service(), after)

    cursor = run_async_task(execute)
    if cursor is not None:
        cleanup.apply_async(args=[cursor], queue="celery", headers={"tenant_id": 1})


@bisheng_celery.task(name="kunlian.formal_workflow_reconcile", shared=False)
def reconcile(after=None):
    # Existing Beat entry starts an independent bounded cleanup chain, once per scan.
    if after is None:
        cleanup.apply_async(queue="celery", headers={"tenant_id": 1})

    async def execute():
        return await reconcile_batch(await get_kunlian_runtime_service(), after)

    cursor = run_async_task(execute)
    if cursor is not None:
        reconcile.apply_async(args=[cursor], queue="celery", headers={"tenant_id": 1})


def dispatch_run(tenant_id, session_id, interaction_id=None):
    run.apply_async(
        args=[session_id, interaction_id],
        headers={"tenant_id": tenant_id},
        queue="workflow_celery",
    )
