"""管理端用户列表 / 审计列表读路径。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.points.domain.services.points_query_service import PointsQueryService


@pytest.mark.asyncio
async def test_admin_list_users_enriches_name_and_dept():
    repo = SimpleNamespace(
        list_accounts_page=AsyncMock(return_value=([SimpleNamespace(user_id=4, balance=28)], 1)),
        sum_deltas_by_users=AsyncMock(return_value={4: 12}),
    )
    service = PointsQueryService(session=None, repository=repo, ledger=None)
    with (
        patch.object(
            PointsQueryService,
            "_leaderboard_display_maps",
            AsyncMock(return_value=({4: "gzx01"}, {4: "测试111"})),
        ),
        patch(
            "bisheng.points.domain.constants.admin_user_type.resolve_user_types_for_admin_list",
            AsyncMock(return_value={4: "部门库管理员"}),
        ),
    ):
        out = await service.admin_list_users(
            1, SimpleNamespace(is_admin=lambda: True, is_global_super=True), page=1, page_size=20
        )
    assert out.total == 1
    assert out.data[0].user_name == "gzx01"
    assert out.data[0].dept_name == "测试111"
    assert out.data[0].user_type == "部门库管理员"
    assert out.data[0].month_score == 12
    # 月度聚合必须收敛到当页用户，不能退回全租户 GROUP BY。
    assert repo.sum_deltas_by_users.await_args.args[1] == [4]


@pytest.mark.asyncio
async def test_admin_list_users_intersects_dept_and_user_type_filters():
    repo = SimpleNamespace(
        list_accounts_page=AsyncMock(return_value=([SimpleNamespace(user_id=4, balance=28)], 1)),
        sum_deltas_by_users=AsyncMock(return_value={4: 5}),
        list_account_user_ids=AsyncMock(return_value=[4, 7]),
    )
    service = PointsQueryService(session=None, repository=repo, ledger=None)
    with (
        patch.object(
            PointsQueryService,
            "_leaderboard_display_maps",
            AsyncMock(return_value=({4: "u4"}, {4: "dept-a"})),
        ),
        patch(
            "bisheng.points.domain.constants.admin_user_type.resolve_user_types_for_admin_list",
            AsyncMock(return_value={4: "公共库管理员"}),
        ),
        patch(
            "bisheng.database.models.department.UserDepartmentDao.aget_user_ids_by_department",
            AsyncMock(return_value=[4, 9]),
        ),
        patch(
            "bisheng.points.domain.constants.admin_user_type.resolve_user_ids_for_user_type_filter",
            AsyncMock(return_value=[4, 7]),
        ),
    ):
        out = await service.admin_list_users(
            1,
            SimpleNamespace(is_admin=lambda: True, is_global_super=True),
            dept_id=10,
            user_type="公共库管理员",
            page=1,
            page_size=20,
        )
    assert out.total == 1
    assert out.data[0].user_type == "公共库管理员"
    repo.list_accounts_page.assert_awaited()
    assert repo.list_accounts_page.await_args.kwargs["user_ids"] == [4]


@pytest.mark.asyncio
async def test_admin_user_filter_options_returns_departments_and_roles():
    service = PointsQueryService(session=None, repository=SimpleNamespace(), ledger=None)
    fake_dept = SimpleNamespace(id=3, name="研发部", short_name=None)
    with patch(
        "bisheng.database.models.department.DepartmentDao.aget_all_active",
        AsyncMock(return_value=[fake_dept]),
    ):
        out = await service.admin_user_filter_options(
            SimpleNamespace(is_admin=lambda: True, is_global_super=True),
        )
    assert out.departments[0].id == 3
    assert out.departments[0].name == "研发部"
    assert "普通用户" in out.user_types
    assert "公共库管理员" in out.user_types


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
        AsyncMock(return_value=({1: "admin01", 4: "gzx01"}, {})),
    ):
        out = await service.admin_list_audit_logs(1, SimpleNamespace(is_admin=lambda: True, is_global_super=True))
    assert out.total == 1
    assert out.data[0].source == "manual_adjust"
    assert out.data[0].user_name == "gzx01"
    assert out.data[0].operator_name == "admin01"
    repo.list_audit_logs.assert_awaited()
    kwargs = repo.list_audit_logs.await_args.kwargs
    assert kwargs["sources"] == ["manual_adjust", "manual_deduct"]


@pytest.mark.asyncio
async def test_admin_user_detail_returns_summary_and_filtered_logs():
    """管理端用户详情：概况卡片 + 时间窗全量流水。"""
    from datetime import datetime

    log_row = SimpleNamespace(
        id=3,
        title="发布文档到部门库",
        delta=2,
        balance_after=1280,
        direction="earn",
        rule_code="E01",
        source="rule",
        remark=None,
        occurred_at=datetime(2024, 1, 15, 10, 30, 1),
    )
    repo = SimpleNamespace(
        find_account=AsyncMock(return_value=SimpleNamespace(balance=1280)),
        sum_user_delta=AsyncMock(side_effect=[215, -0]),
        list_logs=AsyncMock(return_value=([log_row], 1)),
    )
    service = PointsQueryService(session=None, repository=repo, ledger=None)
    admin = SimpleNamespace(is_admin=lambda: True, is_global_super=True)
    with (
        patch.object(
            PointsQueryService,
            "_leaderboard_display_maps",
            AsyncMock(return_value=({7: "张三"}, {7: "技术研发部"})),
        ),
        patch(
            "bisheng.points.domain.constants.admin_user_type.resolve_user_types_for_admin_list",
            AsyncMock(return_value={7: "普通用户"}),
        ),
    ):
        out = await service.admin_user_detail(
            1,
            admin,
            7,
            page=1,
            page_size=20,
            from_time=datetime(2024, 1, 1),
            to_time=datetime(2024, 2, 1),
        )

    assert out.user_name == "张三"
    assert out.dept_name == "技术研发部"
    assert out.role_label == "普通用户"
    assert out.balance == 1280
    assert out.month_earned == 215
    assert out.month_deducted == 0
    assert out.logs_total == 1
    assert out.logs[0].title == "发布文档到部门库"
    assert out.logs[0].delta == 2
    repo.list_logs.assert_awaited()
    assert repo.list_logs.await_args.args[1] == 7
    assert repo.sum_user_delta.await_count == 2
