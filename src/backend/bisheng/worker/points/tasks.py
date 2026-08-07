"""积分模块 Celery Beat 任务：排行、月奖、对账与 outbox。"""

from __future__ import annotations

import logging

from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery

logger = logging.getLogger(__name__)


@bisheng_celery.task(
    acks_late=True,
    time_limit=1800,
    soft_time_limit=1500,
    name="bisheng.worker.points.tasks.refresh_points_rank_snapshots",
)
def refresh_points_rank_snapshots():
    """每小时刷新积分榜快照；受 points.rank_cron_enabled 控制。"""
    return run_async_task(_refresh_rank_async)


async def _refresh_rank_async() -> dict:
    """异步刷新排行入口；cron 关闭时直接跳过。"""
    from bisheng.common.services.config_service import settings
    from bisheng.points.domain.services.points_rank_service import PointsRankService

    conf = getattr(settings, "points", None)
    if conf is not None and not bool(getattr(conf, "rank_cron_enabled", True)):
        logger.info("points.rank.cron_disabled skip refresh")
        return {"skipped": True}
    result = await PointsRankService().refresh_all_tenants()
    logger.info("points.rank.cron_done %s", result)
    return result


@bisheng_celery.task(
    acks_late=True,
    time_limit=3600,
    soft_time_limit=3300,
    name="bisheng.worker.points.tasks.run_monthly_admin_rewards",
)
def run_monthly_admin_rewards():
    """每月 1 日发放上月管理员月奖；受 points.monthly_reward_enabled 控制。"""
    return run_async_task(_monthly_reward_async)


async def _monthly_reward_async() -> dict:
    """异步月奖入口。"""
    from bisheng.common.services.config_service import settings
    from bisheng.points.domain.services.points_monthly_reward_service import (
        PointsMonthlyRewardService,
    )

    conf = getattr(settings, "points", None)
    if conf is not None and not bool(getattr(conf, "monthly_reward_enabled", True)):
        logger.info("points.monthly.cron_disabled skip")
        return {"skipped": True}
    result = await PointsMonthlyRewardService().run_all_tenants()
    logger.info("points.monthly.cron_done %s", result)
    return result


@bisheng_celery.task(
    acks_late=True,
    time_limit=1800,
    soft_time_limit=1500,
    name="bisheng.worker.points.tasks.reconcile_point_balances",
)
def reconcile_point_balances():
    """每日对账：sum(log.delta) 与 account.balance；只告警不改流水。"""
    return run_async_task(_reconcile_async)


async def _reconcile_async() -> dict:
    """异步对账入口。"""
    from bisheng.points.domain.services.points_reconcile_service import PointsReconcileService

    result = await PointsReconcileService().reconcile_all_tenants()
    logger.info("points.reconcile.cron_done %s", result)
    return result


@bisheng_celery.task(
    acks_late=True,
    time_limit=1800,
    soft_time_limit=1500,
    name="bisheng.worker.points.tasks.drain_points_sync_outbox",
)
def drain_points_sync_outbox():
    """消费积分同步 outbox；sync_outbox_enabled=false 时保持 pending。"""
    return run_async_task(_drain_outbox_async)


async def _drain_outbox_async() -> dict:
    """异步 outbox drain 入口。"""
    from bisheng.points.domain.services.points_sync_outbox_service import PointsSyncOutboxService

    result = await PointsSyncOutboxService().drain()
    logger.info("points.outbox.cron_done %s", result)
    return result
