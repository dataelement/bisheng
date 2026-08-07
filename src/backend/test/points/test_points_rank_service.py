"""积分排行快照：周期键、部门桶解析与排序。"""

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from bisheng.points.domain.services.points_rank_service import (
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
