"""Celery beat task: periodically reconcile stale resource_permission_mode rows.

Runs every 10 minutes via beat schedule. Finds rows whose parent_type/parent_id
disagrees with the business-truth parent computed from knowledgefile.file_level_path
and re-projects them via project_parent_change.

Concurrent safety: no distributed lock is needed because ``project_parent_change``
is idempotent — it raises ``PermissionInvalidResourceError`` when old and new
parents are already equal.  Concurrent beat runs may produce duplicate log lines
but cannot corrupt data.
"""

from __future__ import annotations

import logging

from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery

logger = logging.getLogger(__name__)


@bisheng_celery.task(acks_late=True)
def reconcile_stale_parent_projections():
    """Periodic task: find and repair stale permission projections."""
    run_async_task(_reconcile)


async def _reconcile() -> int:
    from bisheng.knowledge.domain.services.stale_projection_reconciler import (
        reconcile_stale_parent_projections,
    )

    return await reconcile_stale_parent_projections(batch_limit=200)
