"""排行榜读路径：按当前用户公司隔离 + 展示字段补齐。"""

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
    with (
        patch.object(
            PointsQueryService,
            "_resolve_user_company_id",
            AsyncMock(return_value=100),
        ),
        patch.object(
            PointsQueryService,
            "_leaderboard_display_maps",
            AsyncMock(return_value=({10: "张三"}, {10: "炼铁作业部"})),
        ),
    ):
        out = await service.leaderboard(1, "month", user_id=10)

    assert out.period == "month"
    assert len(out.items) == 1
    assert out.items[0].user_name == "张三"
    assert out.items[0].dept_name == "炼铁作业部"
    assert out.items[0].period_score == 40
    repo.list_top_ranks.assert_awaited_once()
    assert repo.list_top_ranks.await_args.args[3] == 100  # scope_id=company_id


@pytest.mark.asyncio
async def test_leaderboard_empty_when_user_has_no_company():
    """无公司归属：首页榜空态，不查 TOP 快照。"""
    repo = SimpleNamespace(
        list_top_ranks=AsyncMock(return_value=[]),
        latest_rank_refreshed_at=AsyncMock(return_value=None),
    )
    service = PointsQueryService(session=None, repository=repo, ledger=None)
    with patch.object(
        PointsQueryService,
        "_resolve_user_company_id",
        AsyncMock(return_value=None),
    ):
        out = await service.leaderboard(1, "month", user_id=10)

    assert out.items == []
    repo.list_top_ranks.assert_not_awaited()
