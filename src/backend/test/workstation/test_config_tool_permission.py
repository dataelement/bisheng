"""The workbench only offers tools the signed-in user is allowed to run.

An admin curates the daily tool list, but every tool keeps its own resource
permission — `ToolExecutor` refuses the call at request time — so a tool the
user cannot use must not appear in the picker at all.
"""

import pytest

from bisheng.workstation.domain.services.workstation_service import WorkStationService

GROUPS = [
    {"id": 362, "name": "地图", "children": [{"id": 2125}]},
    {"id": 627, "name": "0716", "children": [{"id": 2831}]},
]


@pytest.fixture
def login_user():
    class _User:
        user_id = 840
        user_name = "wangxinlei2"

    return _User()


async def test_keeps_only_usable_groups(monkeypatch, login_user):
    async def fake_batch(user, *, resource_type, resource_ids, actions):
        assert resource_type == "tool"
        assert actions == ("use",)
        assert sorted(resource_ids) == [362, 627]
        return {"362": frozenset({"use"})}

    monkeypatch.setattr(
        "bisheng.permission.application.business_authorization.batch_check_business_actions",
        fake_batch,
    )

    kept = await WorkStationService.afilter_tools_by_use_permission(GROUPS, login_user)

    assert [group["id"] for group in kept] == [362]


async def test_empty_input_short_circuits(monkeypatch, login_user):
    async def fail_batch(*args, **kwargs):
        raise AssertionError("permission check must not run for an empty list")

    monkeypatch.setattr(
        "bisheng.permission.application.business_authorization.batch_check_business_actions",
        fail_batch,
    )

    assert await WorkStationService.afilter_tools_by_use_permission([], login_user) == []
    assert await WorkStationService.afilter_tools_by_use_permission(None, login_user) == []


async def test_group_without_id_is_dropped(monkeypatch, login_user):
    async def fake_batch(user, *, resource_type, resource_ids, actions):
        assert list(resource_ids) == [627]
        return {"627": frozenset({"use"})}

    monkeypatch.setattr(
        "bisheng.permission.application.business_authorization.batch_check_business_actions",
        fake_batch,
    )

    groups = [{"name": "no id"}, {"id": 627, "name": "0716"}]

    kept = await WorkStationService.afilter_tools_by_use_permission(groups, login_user)

    assert [group["id"] for group in kept] == [627]
