"""Celery beat task: remove workspaces of expired temporary agent sessions (F078).

Reads only MinIO and Redis, never a business table, so it needs no tenant
context and cannot miss a tenant.
"""

from __future__ import annotations

from bisheng.worker.main import bisheng_celery


@bisheng_celery.task(acks_late=True)
def sweep_agent_tmp_sessions() -> int:
    from bisheng.worker._asyncio_utils import run_async_task

    return run_async_task(_sweep)


async def _sweep() -> int:
    from bisheng.agent_runtime.domain.services.tmp_session import TmpSessionService
    from bisheng.core.cache.redis_manager import get_redis_client
    from bisheng.core.storage.minio.minio_manager import get_minio_storage

    service = TmpSessionService(redis=await get_redis_client(), minio=await get_minio_storage())
    return await service.asweep_expired()
