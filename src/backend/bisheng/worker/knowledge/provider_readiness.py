"""Promote accepted provider uploads once the provider itself finished processing.

The upload ledger records acceptance, not completion: WeKnora parses, indexes
and enriches asynchronously afterwards. Until that readback succeeds the local
file must stay visible but unusable (``received``), and the listing shows it as
queued. This scan is the only place that closes that gap.
"""

from loguru import logger

from bisheng.core.context.tenant import bypass_tenant_filter, tenant_execution_scope
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.application.provider_processing_proof import read_weknora_processing_proof
from bisheng.knowledge.application.provider_processing_readiness import reconcile_processed_upload
from bisheng.knowledge.application.provider_v1_runtime import ProviderFeatureUnavailable
from bisheng.knowledge.domain.repositories.provider_processing_readiness_repository import (
    ProcessingReadinessRepository,
)
from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.information.reconcile import _active_tenant_ids
from bisheng.worker.main import bisheng_celery

BATCH_PER_TENANT = 50


def _proof_reader(actor_user_id):
    async def proof(target):
        return await read_weknora_processing_proof(target, actor_user_id=actor_user_id)

    return proof


async def reconcile_tenant(tenant_id: int, *, limit: int = BATCH_PER_TENANT) -> int:
    """One bounded pass; each upload is independent so one failure cannot stall the rest."""
    with tenant_execution_scope(tenant_id):
        async with get_async_db_session() as session:
            pending = await ProcessingReadinessRepository().alist_pending(session, tenant_id=tenant_id, limit=limit)
        promoted = 0
        for operation_id, actor_user_id in pending:
            try:
                if await reconcile_processed_upload(operation_id=operation_id, read_proof=_proof_reader(actor_user_id)):
                    promoted += 1
            except ProviderFeatureUnavailable:
                # Capability, credential or route is not usable right now; the
                # file stays queued and the next scan retries it.
                logger.warning("provider readiness skipped operation={} (unavailable)", operation_id)
            except Exception:
                # A remote/timeout failure is retryable and must not hide the
                # other uploads waiting in the same tenant.
                logger.opt(exception=True).warning("provider readiness failed operation={}", operation_id)
        return promoted


async def scan() -> int:
    with bypass_tenant_filter():
        tenants = await _active_tenant_ids()
    promoted = 0
    for tenant in tenants:
        promoted += await reconcile_tenant(tenant)
    return promoted


@bisheng_celery.task(queue="knowledge_celery")
def reconcile_provider_uploads():
    return run_async_task(scan)
