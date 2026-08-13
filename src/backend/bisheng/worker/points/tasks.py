"""积分模块 Celery 任务：排行、月奖、对账、outbox 与异步发分。"""

from __future__ import annotations

import logging
from typing import Any

from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery

logger = logging.getLogger(__name__)


@bisheng_celery.task(
    acks_late=True,
    time_limit=120,
    soft_time_limit=60,
    name="bisheng.worker.points.tasks.process_points_award_event",
)
def process_points_award_event(payload: dict[str, Any]):
    """消费自动发分事件；一次上传的多个文件在同一任务内串行入账，幂等键防双发。"""
    return run_async_task(lambda: _process_award_async(payload))


async def _process_award_async(payload: dict[str, Any]) -> dict:
    """在独立会话中执行 Facade 并提交（复用 hooks 同步分发，避免双份 event 映射）。"""
    from bisheng.core.context.tenant import set_current_tenant_id
    from bisheng.points.domain.services.points_award_hooks import _run_payload_sync

    event_type = str(payload.get("event_type") or "")
    if event_type not in {
        "space_file_ready",
        "document_shared",
        "favorite_changed",
        "answer_adopted",
    }:
        logger.error("points.award.unknown_event_type type=%s", event_type)
        return {"ok": False, "reason": "unknown_event_type", "event_type": event_type}

    tenant_id = int(payload["tenant_id"])
    set_current_tenant_id(tenant_id)
    await _run_payload_sync(payload)
    logger.info("points.award.processed event_type=%s", event_type)
    return {"ok": True, "event_type": event_type}


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


@bisheng_celery.task(
    acks_late=True,
    time_limit=1800,
    soft_time_limit=1500,
    name="bisheng.worker.points.tasks.drain_points_pending_deduct",
)
def drain_points_pending_deduct():
    """重试违规删除后失败的补扣队列。"""
    return run_async_task(_drain_pending_deduct_async)


async def _drain_pending_deduct_async() -> dict:
    """异步补扣 drain 入口。"""
    from bisheng.points.domain.services.points_pending_deduct_service import (
        PointsPendingDeductService,
    )

    result = await PointsPendingDeductService().drain()
    logger.info("points.pending_deduct.cron_done %s", result)
    return result
