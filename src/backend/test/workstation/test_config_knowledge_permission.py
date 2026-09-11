from types import SimpleNamespace
from unittest.mock import AsyncMock

from bisheng.api.v1.schemas import OrgKbConfig, WorkstationConfig
from bisheng.workstation.api.endpoints import config as config_endpoint
from bisheng.workstation.domain.services.workstation_service import WorkStationService


def _login_user():
    return SimpleNamespace(user_id=840, user_name="regular-user")


async def test_public_config_keeps_only_visible_org_kbs(monkeypatch):
    login_user = _login_user()
    daily_config = WorkstationConfig(
        orgKbs=[
            OrgKbConfig(id=12, name="hidden", default_checked=True, sort_order=0),
            OrgKbConfig(id=13, name="visible", default_checked=True, sort_order=1),
        ]
    )

    async def fake_batch(user, *, resource_type, resource_ids, actions):
        assert user is login_user
        assert resource_type == "knowledge_library"
        assert list(resource_ids) == [12, 13]
        assert actions == ("visible",)
        # Deliberately omit `use`: this boundary is about visibility only.
        return {"12": frozenset(), "13": frozenset({"visible"})}

    monkeypatch.setattr(
        "bisheng.permission.application.business_authorization.batch_check_business_actions",
        fake_batch,
    )
    monkeypatch.setattr(
        WorkStationService,
        "get_daily_chat_config",
        AsyncMock(return_value=daily_config),
    )
    monkeypatch.setattr(
        WorkStationService,
        "get_linsight_config",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        WorkStationService,
        "get_knowledge_space_config",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        WorkStationService,
        "get_subscription_config",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        config_endpoint,
        "bisheng_settings",
        SimpleNamespace(
            async_get_knowledge=AsyncMock(return_value=SimpleNamespace(image_parser_enabled=False)),
            aget_all_config=AsyncMock(return_value={}),
            aget_linsight_conf=AsyncMock(return_value=SimpleNamespace(waiting_list_url=None)),
        ),
    )

    response = await config_endpoint.get_config(request=None, login_user=login_user)

    assert [item["id"] for item in response.data["orgKbs"]] == [13]
    assert response.data["orgKbs"][0]["default_checked"] is True


async def test_org_kb_visibility_filter_short_circuits_empty_input(monkeypatch):
    async def fail_batch(*args, **kwargs):
        raise AssertionError("permission check must not run for an empty list")

    monkeypatch.setattr(
        "bisheng.permission.application.business_authorization.batch_check_business_actions",
        fail_batch,
    )

    assert await WorkStationService.afilter_org_kbs_by_visible_permission([], _login_user()) == []
    assert await WorkStationService.afilter_org_kbs_by_visible_permission(None, _login_user()) == []
