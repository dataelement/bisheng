"""Celery tasks for org sync (F009).

- execute_org_sync: async sync execution, dispatched by API or beat.
- check_org_sync_schedules: beat task, checks active cron configs every 60s.

Tenant context: propagated via Celery headers (INV-8), automatically restored
by the before_task signal in bisheng.worker.tenant_context.
"""

import asyncio
import logging
from datetime import datetime

from bisheng.worker.main import bisheng_celery

logger = logging.getLogger(__name__)


@bisheng_celery.task(acks_late=True, time_limit=1800, soft_time_limit=1500)
def execute_org_sync(config_id: int, trigger_type: str, trigger_user: int = None):
    """Execute org sync for a given config. Runs in knowledge_celery queue."""
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_execute_org_sync_async(
            config_id, trigger_type, trigger_user,
        ))
    finally:
        loop.close()


async def _execute_org_sync_async(
    config_id: int, trigger_type: str, trigger_user: int = None,
):
    from bisheng.org_sync.domain.services.org_sync_service import OrgSyncService
    try:
        log_id = await OrgSyncService.execute_sync(
            config_id, trigger_type, trigger_user,
        )
        logger.info(f'Org sync completed for config {config_id}, log_id={log_id}')
    except Exception:
        logger.exception(f'Org sync failed for config {config_id}')


@bisheng_celery.task(acks_late=True)
def check_org_sync_schedules():
    """Beat task: check active cron configs and dispatch if due.

    Runs every 60s. Uses croniter to evaluate cron expressions.
    """
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_check_schedules_async())
    finally:
        loop.close()


async def _check_schedules_async():
    from bisheng.org_sync.domain.models.org_sync import OrgSyncConfigDao

    try:
        from croniter import croniter
    except ImportError:
        logger.error('croniter not installed, org sync cron scheduling disabled')
        return

    configs = await OrgSyncConfigDao.aget_active_cron_configs()
    now = datetime.now()

    for config in configs:
        if not config.cron_expression:
            continue
        try:
            cron = croniter(config.cron_expression, config.last_sync_at or now)
            next_run = cron.get_next(datetime)
            if next_run <= now:
                # Due for execution — dispatch
                logger.info(
                    f'Dispatching scheduled sync for config {config.id} '
                    f'(cron={config.cron_expression})',
                )
                execute_org_sync.apply_async(
                    args=[config.id, 'scheduled', None],
                    queue='knowledge_celery',
                )
        except Exception as e:
            logger.warning(
                f'Cron evaluation failed for config {config.id}: {e}',
            )
