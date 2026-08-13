"""积分后台临时任务触发：复用 Beat 同款 Service，无鉴权（用完即删）。"""

from __future__ import annotations

import re

from bisheng.common.errcode.points import PointsInvalidAdjustError
from bisheng.core.context.tenant import set_current_tenant_id
from bisheng.points.domain.services.points_monthly_reward_service import PointsMonthlyRewardService
from bisheng.points.domain.services.points_rank_service import PointsRankService

_PERIOD_KEY_RE = re.compile(r"^\d{4}-\d{2}$")


class PointsAdminJobsService:
    """供测试/联调手动触发积分榜刷新与管理员月奖（不影响 Celery Beat）。"""

    async def refresh_rank_snapshots_for_tenant(self, tenant_id: int) -> dict:
        """
        刷新指定租户月/年/总榜快照。

        :param tenant_id: 目标租户 ID
        :returns: ``PointsRankService.refresh_rank_snapshots`` 原样结果
        """
        set_current_tenant_id(int(tenant_id))
        return await PointsRankService().refresh_rank_snapshots(int(tenant_id))

    async def run_monthly_rewards_for_tenant(
        self,
        tenant_id: int,
        *,
        period_key: str | None = None,
    ) -> dict:
        """
        对指定租户结算管理员月奖。

        :param tenant_id: 目标租户 ID
        :param period_key: 可选 ``YYYY-MM``，默认上月（与 Beat 相同）
        :returns: ``PointsMonthlyRewardService.run_for_tenant`` 原样结果
        """
        if period_key is not None and not _PERIOD_KEY_RE.match(period_key.strip()):
            raise PointsInvalidAdjustError(msg="period_key 须为 YYYY-MM 格式")
        set_current_tenant_id(int(tenant_id))
        key = period_key.strip() if period_key else None
        return await PointsMonthlyRewardService().run_for_tenant(int(tenant_id), period_key=key)
