from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.workstation.api.endpoints import apps as apps_endpoint


@pytest.mark.asyncio
async def test_recommended_apps_passes_async_writeable_ids_to_enrichment():
    login_user = SimpleNamespace(is_admin=lambda: False)
    visible_apps = [{"id": "wf-1"}]

    with (
        patch.object(
            apps_endpoint.WorkStationService,
            "aget_config",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(recommendedApps=["wf-1"]),
        ),
        patch.object(
            apps_endpoint.FlowDao,
            "get_all_apps",
            return_value=(visible_apps, 1),
        ),
        patch.object(
            apps_endpoint.WorkFlowService,
            "filter_apps_by_action",
            new_callable=AsyncMock,
            return_value=visible_apps,
        ),
        patch.object(
            apps_endpoint.WorkFlowService,
            "aget_writeable_app_ids",
            new_callable=AsyncMock,
            return_value=set(),
        ) as mock_writeable_ids,
        patch.object(
            apps_endpoint.WorkFlowService,
            "add_extra_field",
            return_value=visible_apps,
        ) as mock_add_extra_field,
        patch.object(
            apps_endpoint.WorkFlowService,
            "aenrich_apps_can_share",
            new_callable=AsyncMock,
            return_value=visible_apps,
        ),
    ):
        response = await apps_endpoint.get_recommended_apps(login_user=login_user)

    mock_writeable_ids.assert_awaited_once_with(login_user, visible_apps)
    mock_add_extra_field.assert_called_once_with(login_user, visible_apps, writeable_ids=set())
    assert response.data == visible_apps
