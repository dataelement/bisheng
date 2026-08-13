"""积分后台临时任务 HTTP 入口（无鉴权，单租户 query）。"""

from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.errcode.points import PointsInvalidAdjustError
from bisheng.points.domain.services.points_admin_jobs_service import PointsAdminJobsService


@pytest.mark.asyncio
async def test_refresh_rank_snapshots_delegates_to_rank_service():
    service = PointsAdminJobsService()
    with patch("bisheng.points.domain.services.points_admin_jobs_service.PointsRankService") as rank_cls:
        rank_cls.return_value.refresh_rank_snapshots = AsyncMock(return_value={"tenant_id": 1, "rows": 3})
        out = await service.refresh_rank_snapshots_for_tenant(1)
    assert out["rows"] == 3
    rank_cls.return_value.refresh_rank_snapshots.assert_awaited_once_with(1)


@pytest.mark.asyncio
async def test_run_monthly_rewards_delegates_to_monthly_service():
    service = PointsAdminJobsService()
    with patch("bisheng.points.domain.services.points_admin_jobs_service.PointsMonthlyRewardService") as monthly_cls:
        monthly_cls.return_value.run_for_tenant = AsyncMock(
            return_value={"tenant_id": 1, "period_key": "2026-07", "awarded": 2, "skipped": 0}
        )
        out = await service.run_monthly_rewards_for_tenant(1, period_key="2026-07")
    assert out["awarded"] == 2
    monthly_cls.return_value.run_for_tenant.assert_awaited_once_with(1, period_key="2026-07")


@pytest.mark.asyncio
async def test_run_monthly_rewards_rejects_bad_period_key():
    service = PointsAdminJobsService()
    with pytest.raises(PointsInvalidAdjustError):
        await service.run_monthly_rewards_for_tenant(1, period_key="202607")
