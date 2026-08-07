"""Tenant-aware Celery tasks for automotive sheet intro sync (F049).

Root Beat only fans out; every tenant child task carries an explicit
``tenant_id`` header that ``worker/tenant_context.py`` restores into the
ContextVar, so all downstream repos see the right tenant.
"""

from __future__ import annotations

from loguru import logger

from bisheng.core.context.tenant import DEFAULT_TENANT_ID, get_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.database.models.tenant import TenantDao
from bisheng.open_endpoints.domain.schemas.automotive_sheet_intro_sync import AutomotiveSheetIntroSyncTriggerType
from bisheng.open_endpoints.domain.services.automotive_sheet_intro_sync_service import AutomotiveSheetIntroSyncService
from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery

DEFAULT_QUEUE = "celery"


def _dispatch_task_for_tenants(
    task,
    tenant_ids: list[int],
    *,
    trigger_type: AutomotiveSheetIntroSyncTriggerType = "scheduled",
) -> None:
    for tenant_id in sorted({int(value) for value in tenant_ids if int(value) > 0}):
        task.apply_async(
            headers={"tenant_id": tenant_id},
            queue=DEFAULT_QUEUE,
            kwargs={"trigger_type": trigger_type},
        )


async def _run_async(trigger_type: AutomotiveSheetIntroSyncTriggerType = "scheduled") -> str:
    tenant_id = int(get_current_tenant_id() or DEFAULT_TENANT_ID)
    async with get_async_db_session() as session:
        service = AutomotiveSheetIntroSyncService(session=session)
        result = await service.run(tenant_id=tenant_id, trigger_type=trigger_type)
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            raise
    logger.info(
        "automotive sheet intro sync worker finished tenant_id={} trigger_type={} status={}",
        tenant_id,
        trigger_type,
        result.status,
    )
    return result.status


@bisheng_celery.task(
    bind=True,
    name="bisheng.open_endpoints.worker.filelib_sync_worker.run_automotive_sheet_intro_sync",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
    time_limit=1800,
    acks_late=True,
)
def run_automotive_sheet_intro_sync(_task, trigger_type: AutomotiveSheetIntroSyncTriggerType = "scheduled"):
    return run_async_task(lambda: _run_async(trigger_type))


async def _fanout_async() -> int:
    tenant_ids = [DEFAULT_TENANT_ID, *(await TenantDao.aget_children_ids_active(DEFAULT_TENANT_ID))]
    _dispatch_task_for_tenants(run_automotive_sheet_intro_sync, tenant_ids)
    return len(set(tenant_ids))


@bisheng_celery.task(
    name="bisheng.open_endpoints.worker.filelib_sync_worker.fanout_automotive_sheet_intro_sync",
)
def fanout_automotive_sheet_intro_sync():
    return run_async_task(_fanout_async)
