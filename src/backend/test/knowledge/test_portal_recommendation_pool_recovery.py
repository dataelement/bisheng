from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.knowledge.domain.services.portal_recommendation_pool_recovery_service import (
    PortalRecommendationPoolRecoveryService,
)


@pytest.mark.asyncio
async def test_missing_active_pool_enqueues_only_once_inside_rebuild_lock_window():
    repository = SimpleNamespace(
        acquire_pool_rebuild_trigger=AsyncMock(side_effect=[True, False]),
    )
    enqueue = MagicMock()
    first = await PortalRecommendationPoolRecoveryService.trigger_if_needed(
        repository,
        5,
        enqueue=enqueue,
    )
    second = await PortalRecommendationPoolRecoveryService.trigger_if_needed(
        repository,
        5,
        enqueue=enqueue,
    )

    assert (first, second) == (True, False)
    enqueue.assert_called_once_with(5)
