# ruff: noqa: RUF002
"""专家问答 Celery 任务：转公开到期扫描。"""

from __future__ import annotations

import logging

from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery

logger = logging.getLogger(__name__)

EXPIRE_PUBLISH_TASK = "bisheng.worker.qa_expert.tasks.expire_publish_requests"
EXPIRE_PUBLISH_INTERVAL_SECONDS = 60


def register_qa_expert_beat_schedule() -> None:
    """注册转公开过期 Beat。"""
    schedule = dict(bisheng_celery.conf.beat_schedule or {})
    schedule.setdefault(
        "qa_expert_expire_publish_requests",
        {
            "task": EXPIRE_PUBLISH_TASK,
            "schedule": EXPIRE_PUBLISH_INTERVAL_SECONDS,
        },
    )
    bisheng_celery.conf.beat_schedule = schedule


register_qa_expert_beat_schedule()


@bisheng_celery.task(
    acks_late=True,
    time_limit=120,
    soft_time_limit=90,
    name=EXPIRE_PUBLISH_TASK,
)
def expire_publish_requests(tenant_id: int = 1) -> int:
    """扫描 pending 且 expire_at<=now 的转公开申请。执行前恢复租户上下文。"""
    return run_async_task(lambda: _expire_async(int(tenant_id)))


async def _expire_async(tenant_id: int) -> int:
    from bisheng.core.context.tenant import set_current_tenant_id
    from bisheng.qa_expert.domain.publish_service import PublishService

    set_current_tenant_id(tenant_id)
    count = await PublishService().expire_pending(tenant_id=tenant_id)
    logger.info("qa_expert.publish.expire tenant_id=%s count=%s", tenant_id, count)
    return count
