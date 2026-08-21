# ruff: noqa: RUF002
"""积分排行快照：周期键、公司/部门桶解析、稠密名次与按公司刷榜。"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest

from bisheng.points.domain.services.points_rank_service import (
    PointsRankService,
    build_ranked_rows,
    period_keys,
    resolve_company_id,
    resolve_dept_bucket_id,
    resolve_first_company_id,
    select_top_n_with_score_ties,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_period_keys_shanghai():
    now = datetime(2026, 8, 7, 10, 0, tzinfo=SHANGHAI)
    assert period_keys(now) == {"month": "2026-08", "year": "2026", "all": "all"}


def test_resolve_company_id_walks_path_to_nearest_company():
    company = SimpleNamespace(id=1, path="/1/", org_level="company")
    dept = SimpleNamespace(id=2, path="/1/2/", org_level="dept")
    office = SimpleNamespace(id=3, path="/1/2/3/", org_level="office")
    departments = {1: company, 2: dept, 3: office}
    primary = SimpleNamespace(id=3, path="/1/2/3/")
    assert resolve_company_id(primary, departments) == 1


def test_resolve_company_id_none_when_unlabeled():
    leaf = SimpleNamespace(id=9, path="/9/", org_level=None)
    departments = {9: leaf}
    primary = SimpleNamespace(id=9, path="/9/")
    assert resolve_company_id(primary, departments) is None
    assert resolve_company_id(None, departments) is None


def test_resolve_first_company_id_follows_org_tree_sort_order():
    """同级按 sort_order：sort 更小的公司是组织架构第一个公司。"""
    root = SimpleNamespace(id=1, path="/1/", org_level=None, sort_order=0)
    later = SimpleNamespace(id=10, path="/1/10/", org_level="company", sort_order=2)
    first = SimpleNamespace(id=20, path="/1/20/", org_level="company", sort_order=0)
    departments = {1: root, 10: later, 20: first}
    assert resolve_first_company_id(departments) == 20


def test_resolve_first_company_id_none_when_unlabeled():
    leaf = SimpleNamespace(id=9, path="/9/", org_level=None, sort_order=0)
    assert resolve_first_company_id({9: leaf}) is None


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


def test_build_ranked_rows_dense_ties_and_excludes_admins():
    """同分稠密同名次：100,100,50 → rank 1,1,2；同分按 last_earned_at 再 user_id。"""
    refreshed = datetime(2026, 8, 7, 5, 0)
    earlier = datetime(2026, 8, 1, 10, 0)
    later = datetime(2026, 8, 2, 10, 0)
    rows = build_ranked_rows(
        tenant_id=1,
        period="month",
        scope="global",
        scope_id=100,
        period_key="2026-08",
        scores={10: 100, 11: 100, 12: 50, 99: 999},
        balances={10: 200, 11: 150, 12: 50, 99: 999},
        dept_ids={10: 2, 11: 2, 12: None, 99: 2},
        exclude_user_ids={99},
        refreshed_at=refreshed,
        last_earned_at={10: later, 11: earlier, 12: earlier},
    )
    # 同分 100：先获得的 user 11 排在 user 10 前。
    assert [r.user_id for r in rows] == [11, 10, 12]
    assert [r.rank_no for r in rows] == [1, 1, 2]
    assert rows[0].period_score == 100
    assert rows[0].scope_id == 100
    assert rows[0].last_earned_at == earlier
    assert rows[2].dept_id is None


def test_select_top_n_with_score_ties_includes_boundary_ties():
    """算法甲：第 10 名分值并列者全部纳入，人数可超过 10。"""
    rows = [
        SimpleNamespace(user_id=i, period_score=score)
        for i, score in enumerate(
            [100, 90, 80, 70, 60, 50, 40, 30, 20, 10, 10, 10, 5],
            start=1,
        )
    ]
    selected = select_top_n_with_score_ties(rows, top_n=10)
    assert [r.user_id for r in selected] == list(range(1, 13))
    assert all(int(r.period_score) >= 10 for r in selected)


@pytest.mark.asyncio
async def test_refresh_scopes_by_company_and_trims_inactive():
    """月/年不补 0 分账户；总榜按积分总和（余额非 0）；按公司写 global/dept 桶。"""
    accounts = [
        SimpleNamespace(user_id=1, balance=100, lifetime_earned=120),
        SimpleNamespace(user_id=2, balance=0, lifetime_earned=40),
        SimpleNamespace(user_id=3, balance=50, lifetime_earned=0),
        SimpleNamespace(user_id=4, balance=80, lifetime_earned=90),
        SimpleNamespace(user_id=5, balance=-36, lifetime_earned=0),
    ]
    # user1/2 公司 A；user4 公司 B；user3 无公司且无本月流水
    month_scores = {1: 30, 2: 0, 4: 20}
    year_scores = {1: 80, 2: 5, 4: 40}

    inserted: list[list] = []
    cleared: list[tuple] = []

    repo = SimpleNamespace(
        list_accounts=AsyncMock(return_value=accounts),
        sum_deltas_by_user=AsyncMock(side_effect=[month_scores, year_scores]),
        clear_period_rank_snapshots=AsyncMock(side_effect=lambda *a, **_k: cleared.append(a) or None),
        bulk_insert_rank_snapshots=AsyncMock(side_effect=lambda rows: inserted.append(list(rows)) or len(rows)),
    )

    with (
        patch.object(PointsRankService, "_load_super_admin_ids", AsyncMock(return_value=set())),
        patch.object(
            PointsRankService,
            "_load_company_and_dept_buckets",
            AsyncMock(
                return_value=(
                    {1: 100, 2: 100, 3: None, 4: 200, 5: 100},
                    {1: 10, 2: 10, 3: None, 4: 20, 5: 10},
                )
            ),
        ),
    ):
        out = await PointsRankService(repository=repo)._refresh_with_repo(repo, 1)

    assert out["rows"] > 0
    assert out["companies"] == 2
    assert len(cleared) == 3  # month / year / all
    assert len(inserted) == 3

    month_rows = inserted[0]
    month_global_a = [r for r in month_rows if r.scope == "global" and r.scope_id == 100]
    month_global_b = [r for r in month_rows if r.scope == "global" and r.scope_id == 200]
    assert {r.user_id for r in month_global_a} == {1, 2}
    assert {r.user_id for r in month_global_b} == {4}
    assert all(r.user_id != 3 for r in month_rows)

    all_rows = inserted[2]
    all_global_a = {r.user_id: r.period_score for r in all_rows if r.scope == "global" and r.scope_id == 100}
    all_global_b = {r.user_id: r.period_score for r in all_rows if r.scope == "global" and r.scope_id == 200}
    assert all_global_a == {1: 100, 5: -36}
    assert all_global_b == {4: 80}


@pytest.mark.asyncio
async def test_refresh_no_company_writes_empty_period_batches():
    """全员无公司时仍清桶，但各 period 插入空列表。"""
    accounts = [SimpleNamespace(user_id=1, balance=100, lifetime_earned=120)]
    inserted: list[list] = []
    repo = SimpleNamespace(
        list_accounts=AsyncMock(return_value=accounts),
        sum_deltas_by_user=AsyncMock(side_effect=[{1: 10}, {1: 20}]),
        clear_period_rank_snapshots=AsyncMock(),
        bulk_insert_rank_snapshots=AsyncMock(side_effect=lambda rows: inserted.append(list(rows)) or len(rows)),
    )
    with (
        patch.object(PointsRankService, "_load_super_admin_ids", AsyncMock(return_value=set())),
        patch.object(
            PointsRankService,
            "_load_company_and_dept_buckets",
            AsyncMock(return_value=({1: None}, {1: None})),
        ),
    ):
        out = await PointsRankService(repository=repo)._refresh_with_repo(repo, 1)

    assert out["companies"] == 0
    assert all(len(batch) == 0 for batch in inserted)
