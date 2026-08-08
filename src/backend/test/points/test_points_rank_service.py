"""积分排行快照：周期键、部门桶解析、排序与裁剪入榜。"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest

from bisheng.points.domain.services.points_rank_service import (
    PointsRankService,
    build_ranked_rows,
    period_keys,
    resolve_dept_bucket_id,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_period_keys_shanghai():
    now = datetime(2026, 8, 7, 10, 0, tzinfo=SHANGHAI)
    assert period_keys(now) == {"month": "2026-08", "year": "2026", "all": "all"}


def test_resolve_dept_bucket_walks_path_to_nearest_dept():
    company = SimpleNamespace(id=1, path="/1/", org_level="company")
    dept = SimpleNamespace(id=2, path="/1/2/", org_level="dept")
    office = SimpleNamespace(id=3, path="/1/2/3/", org_level="office")
    departments = {1: company, 2: dept, 3: office}
    primary = SimpleNamespace(id=3, path="/1/2/3/")
    assert resolve_dept_bucket_id(primary, departments) == 2


def test_resolve_dept_bucket_none_when_unlabeled():
    """AC-22: 无向上 dept 标签时不进部门榜。"""
    company = SimpleNamespace(id=1, path="/1/", org_level="company")
    leaf = SimpleNamespace(id=9, path="/1/9/", org_level=None)
    departments = {1: company, 9: leaf}
    primary = SimpleNamespace(id=9, path="/1/9/")
    assert resolve_dept_bucket_id(primary, departments) is None
    assert resolve_dept_bucket_id(None, departments) is None


def test_build_ranked_rows_orders_and_excludes_admins():
    refreshed = datetime(2026, 8, 7, 5, 0)
    rows = build_ranked_rows(
        tenant_id=1,
        period="month",
        scope="global",
        scope_id=None,
        period_key="2026-08",
        scores={10: 100, 11: 100, 12: 50, 99: 999},
        balances={10: 200, 11: 150, 12: 50, 99: 999},
        dept_ids={10: 2, 11: 2, 12: None, 99: 2},
        exclude_user_ids={99},
        refreshed_at=refreshed,
    )
    assert [r.user_id for r in rows] == [10, 11, 12]
    assert [r.rank_no for r in rows] == [1, 2, 3]
    assert rows[0].period_score == 100
    assert rows[2].dept_id is None


@pytest.mark.asyncio
async def test_refresh_trims_zero_balance_and_inactive_month_users():
    """月/年不补 0 分账户；总榜排除 balance=0；有流水净额为 0 仍入月榜。"""
    accounts = [
        SimpleNamespace(user_id=1, balance=100),
        SimpleNamespace(user_id=2, balance=0),
        SimpleNamespace(user_id=3, balance=50),
    ]
    # user1 有变动；user2 本月净 0 但仍有流水；user3 无本月流水
    month_scores = {1: 30, 2: 0}
    year_scores = {1: 80, 2: 5}

    global_batches: list[list] = []
    dept_batches: list[list] = []

    repo = SimpleNamespace(
        list_accounts=AsyncMock(return_value=accounts),
        sum_deltas_by_user=AsyncMock(side_effect=[month_scores, year_scores]),
        replace_rank_snapshots=AsyncMock(
            side_effect=lambda *_a, **_k: global_batches.append(_a[-1]) or len(_a[-1])
        ),
        clear_dept_rank_snapshots=AsyncMock(),
        bulk_insert_rank_snapshots=AsyncMock(
            side_effect=lambda rows: dept_batches.append(list(rows)) or len(rows)
        ),
    )

    with (
        patch.object(PointsRankService, "_load_super_admin_ids", AsyncMock(return_value=set())),
        patch.object(
            PointsRankService,
            "_load_dept_buckets",
            AsyncMock(return_value={1: 10, 2: 10, 3: None}),
        ),
    ):
        out = await PointsRankService(repository=repo)._refresh_with_repo(repo, 1)

    assert out["rows"] > 0
    # 三次 global：month / year / all
    assert len(global_batches) == 3
    month_users = {r.user_id for r in global_batches[0]}
    year_users = {r.user_id for r in global_batches[1]}
    all_users = {r.user_id for r in global_batches[2]}
    assert month_users == {1, 2}
    assert year_users == {1, 2}
    assert all_users == {1, 3}
    assert 2 not in all_users  # balance=0 不进总榜
    assert 3 not in month_users  # 无本月流水不进月榜
