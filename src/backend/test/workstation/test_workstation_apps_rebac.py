"""F048 workstation application authorization regressions."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from bisheng.database.models.flow import FlowStatus, FlowType
from bisheng.workstation.api.endpoints import apps as apps_mod


class _LoginUser:
    user_id = 7
    tenant_id = 1

    def is_admin(self) -> bool:
        return False


async def test_recommended_apps_filter_with_visible_action():
    login_user = _LoginUser()
    configured = ["asst-1", "wf-1"]
    candidates = [
        {"id": "wf-1", "flow_type": FlowType.WORKFLOW.value},
        {"id": "asst-1", "flow_type": FlowType.ASSISTANT.value},
    ]
    filter_by_action = AsyncMock(
        return_value=[
            {"id": "asst-1", "flow_type": FlowType.ASSISTANT.value}
        ]
    )

    with (
        patch.object(
            apps_mod.WorkStationService,
            "aget_config",
            new=AsyncMock(
                return_value=SimpleNamespace(recommendedApps=configured)
            ),
        ),
        patch.object(
            apps_mod.FlowDao,
            "get_all_apps",
            return_value=(candidates, False),
        ) as get_all_apps,
        patch.object(
            apps_mod.WorkFlowService,
            "filter_apps_by_action",
            new=filter_by_action,
        ),
        patch.object(
            apps_mod.WorkFlowService,
            "aget_writeable_app_ids",
            new=AsyncMock(return_value=set()),
        ),
        patch.object(
            apps_mod.WorkFlowService,
            "add_extra_field",
            side_effect=lambda _user, data, **_kwargs: data,
        ),
        patch.object(
            apps_mod.WorkFlowService,
            "aenrich_apps_can_share",
            new=AsyncMock(side_effect=lambda _user, data: data),
        ),
    ):
        result = await apps_mod.get_recommended_apps(
            login_user=login_user
        )

    assert get_all_apps.call_args.kwargs == {
        "id_list": configured,
        "page": 0,
        "limit": 0,
        "status": FlowStatus.ONLINE.value,
    }
    filter_by_action.assert_awaited_once_with(
        login_user,
        candidates,
        "visible",
    )
    assert result.data == [
        {"id": "asst-1", "flow_type": FlowType.ASSISTANT.value}
    ]


async def test_used_apps_filter_with_visible_before_pagination():
    login_user = _LoginUser()
    last_used_at = datetime(2026, 4, 23, 14, 30, 0)
    candidates = [
        {
            "id": "wf-1",
            "flow_type": FlowType.WORKFLOW.value,
            "logo": "",
        },
        {
            "id": "asst-1",
            "flow_type": FlowType.ASSISTANT.value,
            "logo": "",
        },
    ]
    visible = [candidates[0]]
    filter_by_action = AsyncMock(return_value=visible)

    with (
        patch.object(
            apps_mod.MessageSessionDao,
            "get_user_used_apps",
            new=AsyncMock(
                return_value=[
                    ("wf-1", last_used_at),
                    ("asst-1", last_used_at),
                ]
            ),
        ),
        patch.object(
            apps_mod.UserLinkDao,
            "get_user_link",
            return_value=[],
        ),
        patch.object(
            apps_mod.FlowDao,
            "aget_all_apps",
            new=AsyncMock(return_value=(candidates, False)),
        ),
        patch.object(
            apps_mod.WorkFlowService,
            "filter_apps_by_action",
            new=filter_by_action,
        ),
        patch.object(
            apps_mod.WorkFlowService,
            "get_logo_share_link",
            side_effect=lambda logo: logo,
        ),
        patch.object(
            apps_mod.TagDao,
            "get_tags_by_resource",
            return_value={},
        ),
        patch.object(
            apps_mod.WorkFlowService,
            "aenrich_apps_can_share",
            new=AsyncMock(side_effect=lambda _user, data: data),
        ),
    ):
        result = await apps_mod.get_used_apps(
            login_user=login_user,
            page=1,
            limit=20,
        )

    filter_by_action.assert_awaited_once_with(
        login_user,
        candidates,
        "visible",
    )
    assert result.data["total"] == 1
    assert [item["id"] for item in result.data["list"]] == ["wf-1"]


async def test_pin_used_app_requires_use_action():
    login_user = _LoginUser()
    app_info = SimpleNamespace(
        id="wf-1",
        flow_type=FlowType.WORKFLOW.value,
        status=FlowStatus.ONLINE.value,
    )
    check_action = AsyncMock(return_value=True)
    add_user_link = MagicMock(return_value=(None, True))

    with (
        patch.object(
            apps_mod.FlowDao,
            "aget_flow_by_id",
            new=AsyncMock(return_value=app_info),
        ),
        patch.object(
            apps_mod,
            "check_business_action",
            new=check_action,
        ),
        patch.object(
            apps_mod.UserLinkDao,
            "add_user_link",
            new=add_user_link,
        ),
    ):
        await apps_mod.pin_used_app(
            login_user=login_user,
            data=SimpleNamespace(flow_id="wf-1"),
        )

    check_action.assert_awaited_once_with(
        login_user,
        resource_type="workflow",
        resource_id="wf-1",
        action="use",
    )
    add_user_link.assert_called_once()


async def test_pin_used_app_denies_without_use_action():
    login_user = _LoginUser()
    app_info = SimpleNamespace(
        id="asst-1",
        flow_type=FlowType.ASSISTANT.value,
        status=FlowStatus.ONLINE.value,
    )
    add_user_link = MagicMock()

    with (
        patch.object(
            apps_mod.FlowDao,
            "aget_flow_by_id",
            new=AsyncMock(return_value=app_info),
        ),
        patch.object(
            apps_mod,
            "check_business_action",
            new=AsyncMock(return_value=False),
        ),
        patch.object(
            apps_mod.UserLinkDao,
            "add_user_link",
            new=add_user_link,
        ),
    ):
        await apps_mod.pin_used_app(
            login_user=login_user,
            data=SimpleNamespace(flow_id="asst-1"),
        )

    add_user_link.assert_not_called()
