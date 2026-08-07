"""排行榜读路径：展示字段补齐。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.points.domain.services.points_query_service import PointsQueryService


@pytest.mark.asyncio
async def test_leaderboard_enriches_user_and_dept_names():
    repo = SimpleNamespace(
        list_top_ranks=AsyncMock(
            return_value=[
                SimpleNamespace(
                    rank_no=1, user_id=10, balance=100, period_score=40, dept_id=2
                )
            ]
        ),
        latest_rank_refreshed_at=AsyncMock(return_value=None),
    )
    service = PointsQueryService(session=None, repository=repo, ledger=None)
    with patch.object(
        PointsQueryService,
        "_leaderboard_display_maps",
        AsyncMock(return_value=({10: "张三"}, {10: "炼铁作业部"})),
    ):
        out = await service.leaderboard(1, "month")

    assert out.period == "month"
    assert len(out.items) == 1
    assert out.items[0].user_name == "张三"
    assert out.items[0].dept_name == "炼铁作业部"
    assert out.items[0].period_score == 40
