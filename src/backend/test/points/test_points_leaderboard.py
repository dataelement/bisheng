"""排行榜读路径：按当前用户公司隔离 + 展示字段补齐。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.points.domain.services.points_query_service import PointsQueryService


@pytest.mark.asyncio
async def test_leaderboard_enriches_user_and_dept_names():
    repo = SimpleNamespace(
        list_top_ranks=AsyncMock(
            return_value=[SimpleNamespace(rank_no=1, user_id=10, balance=100, period_score=40, dept_id=2)]
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


@pytest.mark.asyncio
async def test_display_maps_uses_org_level_dept_not_leaf():
    """挂在班组叶子上时，展示名取向上最近的 org_level=dept，不回退叶子名。"""
    leaf = SimpleNamespace(id=94, path="/1/54/55/58/67/94/", name="五级积分部门1-1", org_level="squad", short_name=None)
    dept = SimpleNamespace(id=55, path="/1/54/55/", name="二级积分部门1", org_level="dept", short_name=None)
    company = SimpleNamespace(id=54, path="/1/54/", name="测试积分部门", org_level="company", short_name=None)
    office = SimpleNamespace(id=58, path="/1/54/55/58/", name="三级积分部门1", org_level="office", short_name=None)
    squad = SimpleNamespace(id=67, path="/1/54/55/58/67/", name="四级积分部门1", org_level="squad", short_name=None)

    with (
        patch(
            "bisheng.user.domain.models.user.UserDao.aget_user_by_ids",
            AsyncMock(return_value=[SimpleNamespace(user_id=423, user_name="gzx01204")]),
        ),
        patch(
            "bisheng.database.models.department.UserDepartmentDao.get_primary_department_map_by_user_ids",
            return_value={423: leaf},
        ),
        patch(
            "bisheng.database.models.department.DepartmentDao.aget_by_ids",
            AsyncMock(return_value=[company, dept, office, squad]),
        ),
    ):
        names, depts = await PointsQueryService._leaderboard_display_maps([423])

    assert names[423] == "gzx01204"
    assert depts[423] == "二级积分部门1"


@pytest.mark.asyncio
async def test_display_maps_omits_dept_when_no_org_level_dept():
    """path 上没有 dept 标签时不回退叶子名，交给调用方展示 —。"""
    leaf = SimpleNamespace(id=9, path="/1/9/", name="未打标叶子", org_level=None, short_name=None)
    root = SimpleNamespace(id=1, path="/1/", name="默认组织", org_level=None, short_name=None)

    with (
        patch(
            "bisheng.user.domain.models.user.UserDao.aget_user_by_ids",
            AsyncMock(return_value=[SimpleNamespace(user_id=7, user_name="nobody")]),
        ),
        patch(
            "bisheng.database.models.department.UserDepartmentDao.get_primary_department_map_by_user_ids",
            return_value={7: leaf},
        ),
        patch(
            "bisheng.database.models.department.DepartmentDao.aget_by_ids",
            AsyncMock(return_value=[root]),
        ),
    ):
        names, depts = await PointsQueryService._leaderboard_display_maps([7])

    assert names[7] == "nobody"
    assert 7 not in depts


@pytest.mark.asyncio
async def test_display_maps_prefers_short_name_for_dept_bucket():
    """有 dept 桶时展示名优先 short_name。"""
    leaf = SimpleNamespace(id=94, path="/1/54/55/94/", name="叶子", org_level="squad", short_name=None)
    dept = SimpleNamespace(id=55, path="/1/54/55/", name="二级积分部门1", org_level="dept", short_name="质量部")
    company = SimpleNamespace(id=54, path="/1/54/", name="公司", org_level="company", short_name=None)

    with (
        patch(
            "bisheng.user.domain.models.user.UserDao.aget_user_by_ids",
            AsyncMock(return_value=[SimpleNamespace(user_id=423, user_name="gzx")]),
        ),
        patch(
            "bisheng.database.models.department.UserDepartmentDao.get_primary_department_map_by_user_ids",
            return_value={423: leaf},
        ),
        patch(
            "bisheng.database.models.department.DepartmentDao.aget_by_ids",
            AsyncMock(return_value=[company, dept]),
        ),
    ):
        _, depts = await PointsQueryService._leaderboard_display_maps([423])

    assert depts[423] == "质量部"


@pytest.mark.asyncio
async def test_leaderboard_keeps_all_ties_at_tenth_score():
    """第 10 名分值并列时返回超过 10 人，顺序与仓储一致。"""
    bucket = [
        SimpleNamespace(rank_no=i, user_id=i, balance=i, period_score=score, dept_id=1)
        for i, score in enumerate(
            [100, 90, 80, 70, 60, 50, 40, 30, 20, 10, 10, 10],
            start=1,
        )
    ]
    repo = SimpleNamespace(
        list_top_ranks=AsyncMock(return_value=bucket),
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
            AsyncMock(return_value=({i: str(i) for i in range(1, 13)}, dict.fromkeys(range(1, 13), "部"))),
        ),
    ):
        out = await service.leaderboard(1, "month", user_id=1)

    assert len(out.items) == 12
    assert [item.user_id for item in out.items] == list(range(1, 13))
