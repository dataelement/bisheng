"""月奖：结算月、角色奖励与超管排除。"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest

from bisheng.points.domain.constants.monthly_reward_rules import (
    MONTHLY_RULE_MATCHERS,
    fixed_score,
    pick_highest_reward,
)
from bisheng.points.domain.services.points_monthly_reward_service import (
    PointsMonthlyRewardService,
    previous_month_key,
)
from bisheng.points.domain.services.space_fga_roles import SpaceFgaRolesError

SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_previous_month_key_on_first_day():
    now = datetime(2026, 8, 1, 0, 5, tzinfo=SHANGHAI)
    assert previous_month_key(now) == "2026-07"


def test_pick_highest_reward():
    assert pick_highest_reward([("M6", 50), ("M1", 200), ("M4", 100)]) == ("M1", 200)
    assert pick_highest_reward([("M4", 100), ("M6", 100)]) == ("M4", 100)
    assert pick_highest_reward([]) is None
    assert fixed_score({"mode": "fixed", "score": 200}) == 200
    assert fixed_score({"mode": "tier"}) == 0


@pytest.mark.asyncio
async def test_notify_earn_uses_injected_message_service():
    """月奖通知优先使用已注入 MessageService 的 PointsNotifyService。"""
    from bisheng.points.domain.services.points_notify_service import PointsNotifyService

    message = SimpleNamespace(send_generic_notify=AsyncMock())
    service = PointsMonthlyRewardService(notify=PointsNotifyService(message_service=message))
    await service._notify_earn(
        user_id=10,
        rule_code="M1",
        rule_name="公共库所有者月奖",
        delta=200,
    )
    message.send_generic_notify.assert_awaited_once()
    kwargs = message.send_generic_notify.await_args.kwargs
    assert kwargs["receiver_user_ids"] == [10]
    assert kwargs["action_code"] == "points_changed"
    assert kwargs["content_item_list"][0]["content"] == "points_changed"
    assert "200" in kwargs["content_item_list"][0]["metadata"]["points_message"]


@pytest.mark.asyncio
@pytest.mark.parametrize("login_query_error", [False, True], ids=["no-login-records", "telemetry-unavailable"])
async def test_run_for_tenant_awards_without_login_data(login_query_error):
    """无登录记录或统计服务不可用时仍发月奖，平台超管仍排除。"""
    service = PointsMonthlyRewardService()
    es = SimpleNamespace(search=AsyncMock(return_value={"aggregations": {"users": {"buckets": []}}}))
    if login_query_error:
        es.search.side_effect = RuntimeError("telemetry unavailable")
    m1 = SimpleNamespace(
        rule_code="M1",
        name="公共库所有者月奖",
        score_expr={"mode": "fixed", "score": 200},
        status="enabled",
        rule_type="admin_reward",
    )
    m4 = SimpleNamespace(
        rule_code="M4",
        name="部门管理员月奖",
        score_expr={"mode": "fixed", "score": 100},
        status="enabled",
        rule_type="admin_reward",
    )

    async def fake_collect(matchers, rule_by_code):
        return {
            10: ("M1", 200),
            11: ("M4", 100),
            12: ("M1", 200),
        }

    with (
        patch("bisheng.points.domain.services.points_monthly_reward_service.get_async_db_session") as session_factory,
        patch.object(service, "_collect_user_candidates", side_effect=fake_collect),
        patch.object(service, "_load_super_admin_ids", AsyncMock(return_value={12})),
        patch.object(service, "_award_one", AsyncMock(return_value=True)) as award,
        patch(
            "bisheng.core.search.elasticsearch.manager.get_statistics_es_connection",
            AsyncMock(return_value=es),
        ) as get_es,
    ):

        class _Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return False

        session_factory.return_value = _Session()

        class _Repo:
            async def list_rules(self, *_a, **_k):
                return [m1, m4]

        with patch(
            "bisheng.points.domain.services.points_monthly_reward_service.PointsRepository",
            return_value=_Repo(),
        ):
            out = await service.run_for_tenant(1, period_key="2026-07")

    assert out["awarded"] == 2
    assert out["skipped"] == 1
    assert [
        (call.kwargs["user_id"], call.kwargs["rule_code"], call.kwargs["score"]) for call in award.await_args_list
    ] == [
        (10, "M1", 200),
        (11, "M4", 100),
    ]
    get_es.assert_not_awaited()
    es.search.assert_not_awaited()


@pytest.mark.asyncio
async def test_collect_user_candidates_uses_fga_owner_manager():
    """月奖候选人按 OpenFGA owner/manager，不再扫成员表 creator/admin。"""
    service = PointsMonthlyRewardService()
    m1 = SimpleNamespace(
        rule_code="M1",
        score_expr={"mode": "fixed", "score": 200},
    )
    m2 = SimpleNamespace(
        rule_code="M2",
        score_expr={"mode": "fixed", "score": 150},
    )
    matchers = {
        "M1": MONTHLY_RULE_MATCHERS["M1"],
        "M2": MONTHLY_RULE_MATCHERS["M2"],
    }
    rule_by_code = {"M1": m1, "M2": m2}

    with (
        patch(
            "bisheng.points.domain.services.points_monthly_reward_service.KnowledgeSpaceScopeDao.aget_space_ids_by_levels",
            AsyncMock(return_value=[19]),
        ),
        patch(
            "bisheng.points.domain.services.points_monthly_reward_service.read_space_owner_manager_ids",
            AsyncMock(return_value=({220, 1}, {221})),
        ) as read_roles,
    ):
        got = await service._collect_user_candidates(matchers, rule_by_code)

    read_roles.assert_awaited_once_with(19)
    assert got[220] == ("M1", 200)
    assert got[1] == ("M1", 200)
    assert got[221] == ("M2", 150)


@pytest.mark.asyncio
async def test_run_for_tenant_aborts_when_fga_unavailable():
    service = PointsMonthlyRewardService()
    m1 = SimpleNamespace(
        rule_code="M1",
        name="公共库所有者月奖",
        score_expr={"mode": "fixed", "score": 200},
        status="enabled",
        rule_type="admin_reward",
    )

    with (
        patch("bisheng.points.domain.services.points_monthly_reward_service.get_async_db_session") as session_factory,
        patch.object(
            service,
            "_collect_user_candidates",
            AsyncMock(side_effect=SpaceFgaRolesError("down")),
        ),
        patch.object(service, "_award_one", AsyncMock(return_value=True)) as award,
    ):

        class _Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return False

        session_factory.return_value = _Session()

        class _Repo:
            async def list_rules(self, *_a, **_k):
                return [m1]

        with patch(
            "bisheng.points.domain.services.points_monthly_reward_service.PointsRepository",
            return_value=_Repo(),
        ):
            out = await service.run_for_tenant(1, period_key="2026-07")

    assert out["error"] == "fga_unavailable"
    assert out["awarded"] == 0
    award.assert_not_awaited()
