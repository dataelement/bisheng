"""积分外部同步 outbox：投递旁路，失败不回滚账本。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from uuid import uuid4

from bisheng.core.database import get_async_db_session
from bisheng.points.domain.models import PointSyncOutbox
from bisheng.points.domain.repositories.points_repository import PointsRepository

logger = logging.getLogger(__name__)

# 外部协同办公适配器未接入前的占位投递；成功时调用方可返回 True。
DeliverFn = Callable[[PointSyncOutbox], Awaitable[bool]]

MAX_RETRIES = 8


async def _default_deliver(_row: PointSyncOutbox) -> bool:
    """默认无外部适配器：显式失败，由 drain 标为 skipped（非无限重试）。"""
    raise RuntimeError("points_sync_adapter_not_configured")


class PointsSyncOutboxService:
    """消费 point_sync_outbox；开关关闭时保持 pending（AC-23）。"""

    def __init__(self, *, deliver: DeliverFn | None = None):
        self._deliver = deliver or _default_deliver

    async def drain(self, *, limit: int = 100) -> dict:
        """批量投递到期 outbox。"""
        from bisheng.common.services.config_service import settings
        from bisheng.core.context.tenant import bypass_tenant_filter

        conf = getattr(settings, "points", None)
        if conf is None or not bool(getattr(conf, "sync_outbox_enabled", False)):
            logger.info("points.outbox.disabled keep pending")
            return {"skipped": True, "reason": "sync_outbox_disabled"}

        processed = sent = failed = skipped = 0
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                repo = PointsRepository(session)
                await repo.recover_sync_outbox(datetime.utcnow())
                rows = await repo.list_due_sync_outbox(limit=limit)
                ids = [row.id for row in rows]
                await session.commit()
            for row_id in ids:
                owner = uuid4().hex
                async with get_async_db_session() as session:
                    repo = PointsRepository(session)
                    row = await repo.claim_sync_outbox(row_id, owner, datetime.utcnow())
                    snapshot = PointSyncOutbox.model_validate(row.model_dump()) if row else None
                    await session.commit()
                if snapshot is not None:
                    processed += 1
                    # 适配器以稳定 outbox ID 幂等, 超时不代表远端一定未执行。
                    snapshot.payload = {**snapshot.payload, "idempotency_key": f"points-outbox:{snapshot.id}"}
                    async with get_async_db_session() as session:
                        repo = PointsRepository(session)
                        outcome = await self._process_one(repo, snapshot, owner=owner)
                        await session.commit()
                    if outcome == "sent":
                        sent += 1
                    elif outcome == "skipped":
                        skipped += 1
                    else:
                        failed += 1

        result = {
            "processed": processed,
            "sent": sent,
            "failed": failed,
            "skipped": skipped,
        }
        logger.info("points.outbox.drain_done %s", result)
        return result

    async def _process_one(self, repo: PointsRepository, row: PointSyncOutbox, *, owner: str) -> str:
        """投递单条；适配器未配置 → skipped；瞬时失败 → failed+backoff。"""
        try:
            ok = await asyncio.wait_for(self._deliver(row), timeout=60)
            if not ok:
                raise RuntimeError("deliver_returned_false")
            row.status = "sent"
            row.sent_at = datetime.utcnow()
            row.last_error = None
        except Exception as exc:
            message = str(exc)[:500]
            # 未配置适配器：标 skipped，避免永久占用 pending 队列。
            if "points_sync_adapter_not_configured" in message:
                row.status = "skipped"
                row.last_error = message
                row.next_retry_at = None
            elif row.retry_count >= MAX_RETRIES:
                row.status = "dead"
                row.next_retry_at = None
            else:
                row.status = "failed"
                # 指数退避，供下次 drain 捞起（status 仍为 failed 但 next_retry_at 到期）。
                backoff = min(3600, 30 * (2 ** max(row.retry_count - 1, 0)))
                row.next_retry_at = datetime.utcnow() + timedelta(seconds=backoff)
            row.last_error = message
            logger.warning(
                "points.outbox.deliver_failed id=%s retry=%s err=%s",
                row.id,
                row.retry_count,
                message,
            )
        # 外部投递与数据库结算分开, 结算故障不能被误判为投递失败。
        settled = await repo.settle_sync_outbox(row.id, owner, {
            "status": row.status, "sent_at": row.sent_at, "last_error": row.last_error,
            "next_retry_at": None if row.status == "sent" else row.next_retry_at,
        })
        return row.status if settled else "lease_lost"
