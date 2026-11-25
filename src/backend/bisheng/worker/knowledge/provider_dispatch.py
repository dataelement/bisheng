"""Read-only, bounded tenant scans. Broker acceptance never advances the ledger."""

import asyncio

from kombu.exceptions import OperationalError
from loguru import logger

from bisheng.core.context.tenant import bypass_tenant_filter, tenant_execution_scope
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.repositories.provider_operation_repository import ProviderOperationRepository
from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.information.reconcile import _active_tenant_ids
from bisheng.worker.knowledge.provider_operations import (
    PROVIDER_HANDLERS,
    ProviderHandlers,
    advance_provider_operation,
    utcnow,
)
from bisheng.worker.main import bisheng_celery

BATCH_PER_TENANT = 100


async def dispatch_due(*, tenant_id, limit, due, publish):
    sent = 0
    with tenant_execution_scope(tenant_id):
        rows = await due(tenant_id=tenant_id, limit=limit)
        for row in rows:
            if row.tenant_id != tenant_id:
                raise ValueError("due operation outside scan tenant")
            try:
                await publish(
                    operation_id=row.operation_id, expected_revision=row.revision, headers={"tenant_id": tenant_id}
                )
            except (OSError, OperationalError):
                # Broker outcome may be ambiguous; only a later DB claim can consume work.
                logger.warning(
                    "provider wakeup publish unavailable tenant={} operation={}", tenant_id, row.operation_id
                )
                continue
            sent += 1
    return sent


async def _due(*, tenant_id, limit):
    kinds = tuple(kind for kind, handlers in PROVIDER_HANDLERS.items() if isinstance(handlers, ProviderHandlers))
    if not kinds:
        return []
    async with get_async_db_session() as session:
        return await ProviderOperationRepository().list_due(
            session, tenant_id=tenant_id, now=utcnow(), limit=limit, kinds=kinds
        )


async def _publish(*, headers, **kwargs):
    await asyncio.to_thread(
        advance_provider_operation.apply_async, kwargs=kwargs, headers=headers, queue="knowledge_celery", retry=False
    )


async def _scan():
    if not PROVIDER_HANDLERS:
        return 0
    with bypass_tenant_filter():
        tenants = await _active_tenant_ids()
    sent = 0
    for tenant in tenants:
        sent += await dispatch_due(tenant_id=tenant, limit=BATCH_PER_TENANT, due=_due, publish=_publish)
    return sent


@bisheng_celery.task(queue="knowledge_celery")
def dispatch_due_provider_operations():
    return run_async_task(_scan)
