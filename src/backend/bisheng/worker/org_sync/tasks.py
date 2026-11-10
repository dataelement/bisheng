"""Manual org sync — the admin console's "run now" button.

The task only wraps :func:`run_pull_sync`, which fetches the configured
provider's departments/members and applies them through the same service the
Gateway push uses. It is deliberately *not* scheduled: cron-style syncs stay
out of Celery Beat (see ``scripts/wecom_org_sync.py`` and ``sso_sync.md``).
"""

from __future__ import annotations

from loguru import logger

from bisheng.org_sync.domain.services.pull_sync_service import run_pull_sync
from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery


@bisheng_celery.task(
    name="bisheng.worker.org_sync.tasks.execute_org_sync",
    acks_late=True,
)
def execute_org_sync(
    config_id: int,
    trigger_user: int | None = None,
    enqueue_token: str | None = None,
) -> dict:
    """Pull one ``org_sync_config`` now and log the result to ``org_sync_log``."""
    logger.info("org sync task: start config_id={} trigger_user={}", config_id, trigger_user)
    return run_async_task(
        lambda: run_pull_sync(
            config_id,
            trigger_user=trigger_user,
            enqueue_token=enqueue_token,
        )
    )
