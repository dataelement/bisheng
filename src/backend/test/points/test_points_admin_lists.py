"""管理端用户列表 / 审计列表读路径。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.points.domain.services.points_query_service import PointsQueryService


@pytest.mark.asyncio
async def test_admin_list_users_enriches_name_and_dept():
    repo = SimpleNamespace(
        list_accounts_page=AsyncMock(
            return_value=([SimpleNamespace(user_id=4, balance=28)], 1)
        ),
        sum_deltas_by_user=AsyncMock(return_value={4: 12}),
    )
    service = PointsQueryService(session=None, repository=repo, ledger=None)
    with patch.object(
        PointsQueryService,
        "_leaderboard_display_maps",
        AsyncMock(return_value=({4: "gzx01"}, {4: "测试111"})),
    ):
        out = await service.admin_list_users(
            1, SimpleNamespace(is_admin=lambda: True, is_global_super=True), page=1, page_size=20
        )
    assert out.total == 1
    assert out.data[0].user_name == "gzx01"
    assert out.data[0].dept_name == "测试111"
    assert out.data[0].month_score == 12


@pytest.mark.asyncio
async def test_admin_list_audit_logs_filters_manual_sources():
    repo = SimpleNamespace(
        list_audit_logs=AsyncMock(
            return_value=(
                [
                    SimpleNamespace(
                        id=9,
                        user_id=4,
                        title="管理员调分",
                        delta=10,
                        balance_after=38,
                        direction="earn",
                        rule_code="MANUAL",
                        source="manual_adjust",
                        operator_id=1,
                        remark="联调调分验证",
                        occurred_at=None,
                    )
                ],
                1,
            )
        )
    )
    service = PointsQueryService(session=None, repository=repo, ledger=None)
    with patch.object(
        PointsQueryService,
        "_leaderboard_display_maps",
        AsyncMock(return_value=({4: "gzx01"}, {})),
    ):
        out = await service.admin_list_audit_logs(
            1, SimpleNamespace(is_admin=lambda: True, is_global_super=True)
        )
    assert out.total == 1
    assert out.data[0].source == "manual_adjust"
    assert out.data[0].user_name == "gzx01"
    repo.list_audit_logs.assert_awaited()
    kwargs = repo.list_audit_logs.await_args.kwargs
    assert kwargs["sources"] == ["manual_adjust", "manual_deduct"]
