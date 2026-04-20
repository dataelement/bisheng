"""F015 Celery tasks — 6h forced reconcile fan-out + conflict reports.

Three scheduled entries:

- ``reconcile_all_organizations`` (cron ``0 */6 * * *``): fans one
  ``reconcile_single_config`` per active ``org_sync_config``. Skips the
  F014 ``provider='sso_realtime'`` seed.
- ``report_ts_conflicts_weekly`` (cron ``0 9 * * MON``): aggregates the
  past 7d of ``ts_conflict`` event rows and notifies global super
  admins when any external_id crosses
  ``settings.reconcile.weekly_conflict_threshold``.
- ``report_ts_conflicts_daily_escalation`` (cron ``0 9 * * *``):
  escalates to daily notices once the prior weekly report is
  ``settings.reconcile.daily_escalation_days`` old and conflicts
  persist.

Beat registration lives in ``bisheng.core.config.settings.CeleryConf.validate``.

Each task opens its own asyncio loop so Celery's threaded worker pool
doesn't collide with the one currently running inside the dispatcher.
"""

import asyncio
import logging

from bisheng.worker.main import bisheng_celery

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 6h fan-out + per-config executor
# ---------------------------------------------------------------------------


@bisheng_celery.task(acks_late=True)
def reconcile_all_organizations():
    """Fan out ``reconcile_single_config`` for every active config."""
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_fan_out_all())
    finally:
        loop.close()


async def _fan_out_all() -> None:
    """Iterate active configs and dispatch one Celery task per config.

    Dispatch is fire-and-forget — ``apply_async`` returns immediately
    and the single-config worker owns the lock / result. If a config is
    ``provider='sso_realtime'`` it represents the F014 HMAC seed, which
    never talks to a live provider and must be skipped.
    """
    from bisheng.org_sync.domain.models.org_sync import OrgSyncConfigDao

    configs = await OrgSyncConfigDao.aget_all_active()
    for c in configs:
        if c.provider == 'sso_realtime':
            continue
        try:
            reconcile_single_config.apply_async(
                args=[c.id], queue='knowledge_celery',
            )
        except Exception as e:
            logger.exception(
                f'dispatch reconcile_single_config({c.id}) failed: {e}')


@bisheng_celery.task(acks_late=True, time_limit=1800, soft_time_limit=1500)
def reconcile_single_config(config_id: int):
    """Run :meth:`OrgReconcileService.reconcile_config` for one config."""
    from fastapi import HTTPException

    from bisheng.common.errcode.sso_sync import SsoReconcileLockBusyError
    from bisheng.org_sync.domain.services.reconcile_service import (
        OrgReconcileService,
    )

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(
            OrgReconcileService.reconcile_config(config_id)
        )
    except HTTPException as e:
        # SsoReconcileLockBusyError.http_exception() wraps the code as
        # a FastAPI HTTPException, not as the original subclass — match
        # by status_code so the AC-13 precursor swallow path still fires.
        if e.status_code == SsoReconcileLockBusyError.Code:
            logger.warning(
                f'reconcile_single_config({config_id}) skipped: lock busy')
        else:
            logger.exception(
                f'reconcile_single_config({config_id}) http error: {e.detail}')
    except Exception:
        logger.exception(
            f'reconcile_single_config({config_id}) failed')
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Weekly + daily conflict reports (AC-12)
# ---------------------------------------------------------------------------


@bisheng_celery.task(acks_late=True)
def report_ts_conflicts_weekly():
    """Monday 09:00 — aggregate last-7d ts_conflicts, notify admins."""
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_run_weekly())
    finally:
        loop.close()


async def _run_weekly() -> None:
    from bisheng.org_sync.domain.services.ts_conflict_reporter import (
        TsConflictReporter,
    )

    try:
        await TsConflictReporter.weekly_report()
    except Exception:
        logger.exception('TsConflictReporter.weekly_report failed')


@bisheng_celery.task(acks_late=True)
def report_ts_conflicts_daily_escalation():
    """Daily 09:00 — escalate to daily notices when conflicts persist."""
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_run_daily_escalation())
    finally:
        loop.close()


async def _run_daily_escalation() -> None:
    from bisheng.org_sync.domain.services.ts_conflict_reporter import (
        TsConflictReporter,
    )

    try:
        await TsConflictReporter.daily_escalation_report()
    except Exception:
        logger.exception(
            'TsConflictReporter.daily_escalation_report failed')
