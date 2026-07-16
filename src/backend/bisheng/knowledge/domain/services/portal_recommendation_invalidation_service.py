"""Best-effort recommendation invalidation at primary-department write boundaries."""

from __future__ import annotations

import logging
from collections.abc import Iterable

logger = logging.getLogger(__name__)


def invalidate_portal_recommendation_users_best_effort(user_ids: Iterable[int]) -> None:
    normalized_ids = sorted({int(user_id) for user_id in user_ids if int(user_id) > 0})
    if not normalized_ids:
        return
    try:
        from bisheng.worker.knowledge.portal_recommendation import (
            enqueue_portal_recommendation_user_invalidation,
        )

        enqueue_portal_recommendation_user_invalidation(user_ids=normalized_ids)
    except Exception:
        # The primary-department write is authoritative. A temporary broker
        # outage must not roll it back; cache TTL/reconciliation still converge.
        logger.exception(
            "failed to enqueue recommendation invalidation for users=%s",
            normalized_ids,
        )
