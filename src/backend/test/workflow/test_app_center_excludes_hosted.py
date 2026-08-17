"""F056 T010 — hosted applications must not reach the chat-entry lists.

The square is not the only list that runs a candidate set through
``filter_apps_by_action``. "Application centre / frequently used" and the
workbench's recommendation strip do too, and a click there lands on
``/app/{chatId}/{id}/{flow_type}`` — a conversation page. A hosted application
has no conversation semantics at all, so the card would open a blank or broken
screen.

Nothing in F056's acceptance criteria covers that path, which is exactly why it
needs a test: the layer-1 legality filter happens to hide hosted apps only when
the requested action is illegal for them, and these paths ask for ``visible``,
which is legal. The exclusion has to be explicit.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.api.services.workflow import WorkFlowService
from bisheng.database.models.flow import FlowType

HOSTED = FlowType.HOSTED_APP.value
WORKFLOW = FlowType.WORKFLOW.value
ASSISTANT = FlowType.ASSISTANT.value


class _LoginUser:
    user_id = 4201
    user_name = "f056-normal"

    def is_admin(self) -> bool:
        return False


def _candidates() -> list[dict]:
    return [
        {"id": "wf-1", "flow_type": WORKFLOW, "user_id": 1, "logo": ""},
        {"id": "app-1", "flow_type": HOSTED, "user_id": 1, "logo": ""},
        {"id": "asst-1", "flow_type": ASSISTANT, "user_id": 1, "logo": ""},
    ]


@pytest.fixture()
def grant_everything(monkeypatch):
    """Every candidate passes every check, so an absence can only be the type gate."""
    from bisheng.common.services.config_service import settings

    monkeypatch.setattr(settings.app_runtime, "enabled", True)

    async def _batch_check(user, *, resource_type, resource_ids, actions):
        return {str(resource_id): frozenset(actions) for resource_id in resource_ids}

    monkeypatch.setattr(
        "bisheng.api.services.workflow.batch_check_business_actions",
        _batch_check,
    )


async def test_frequently_used_excludes_hosted(grant_everything):
    """Application centre: hosted apps out, the other two in their original order."""
    links = [SimpleNamespace(type_detail=row["id"]) for row in _candidates()]

    with (
        patch(
            "bisheng.api.services.workflow.UserLinkDao.get_user_link",
            return_value=links,
        ),
        patch(
            "bisheng.api.services.workflow.FlowDao.get_all_apps",
            return_value=(_candidates(), 3),
        ),
        patch.object(WorkFlowService, "add_extra_field", side_effect=lambda _user, data, **_kw: data),
        patch.object(WorkFlowService, "aenrich_apps_can_share", new=AsyncMock(side_effect=lambda _user, data: data)),
    ):
        data, total = await WorkFlowService.get_frequently_used_flows(_LoginUser(), "app", 1, 8)

    assert [row["id"] for row in data] == ["wf-1", "asst-1"]
    assert total == 2


async def test_recommended_apps_exclude_hosted(grant_everything):
    """Workbench recommendation strip: an administrator may configure a hosted app anyway."""
    from bisheng.workstation.api.endpoints import apps as apps_endpoint

    with (
        patch.object(
            apps_endpoint.WorkStationService,
            "aget_config",
            new=AsyncMock(return_value=SimpleNamespace(recommendedApps=["wf-1", "app-1", "asst-1"])),
        ),
        patch.object(apps_endpoint.FlowDao, "get_all_apps", return_value=(_candidates(), 3)),
        patch.object(WorkFlowService, "aget_writeable_app_ids", new=AsyncMock(return_value=set())),
        patch.object(WorkFlowService, "add_extra_field", side_effect=lambda _user, data, **_kw: data),
        patch.object(WorkFlowService, "aenrich_apps_can_share", new=AsyncMock(side_effect=lambda _user, data: data)),
    ):
        response = await apps_endpoint.get_recommended_apps(login_user=_LoginUser())

    assert [row["id"] for row in response.data] == ["wf-1", "asst-1"]


async def test_filter_apps_by_action_default_keeps_every_type(grant_everything):
    """The exclusion is opt-in: callers that do not ask keep the old behaviour."""
    kept = await WorkFlowService.filter_apps_by_action(_LoginUser(), _candidates(), "visible")

    assert [row["id"] for row in kept] == ["wf-1", "app-1", "asst-1"]
