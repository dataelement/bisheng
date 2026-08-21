"""Regression test for IKABQ0 — workstation tool list is filtered by the
requester's ``view_tool`` permission.

The bug: an end user without API/MCP tool permission could see the
admin-configured tools in the workspace chat toolbar. The fix
(`WorkStationService._afilter_tools_by_view_permission`) drops tool
groups the requester has no ``view_tool`` permission on before the
config is returned to the client. Admins (super / tenant / child) keep
the unfiltered view so the config page can still echo every tool.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.workstation.domain.services.workstation_service import WorkStationService


def _make_user(is_admin: bool) -> SimpleNamespace:
    return SimpleNamespace(is_admin=lambda: is_admin)


def _make_groups(*type_ids: int) -> list[dict]:
    return [
        {
            "id": tid,
            "name": f"tool-type-{tid}",
            "is_preset": 0,
            "description": "",
            "default_checked": False,
            "children": [
                {
                    "id": tid * 100,
                    "name": f"tool-{tid}",
                    "tool_key": f"tool_key_{tid}",
                    "desc": "",
                }
            ],
        }
        for tid in type_ids
    ]


@pytest.mark.asyncio
async def test_non_admin_without_view_permission_loses_tool():
    """A non-admin user without `view_tool` on a tool must not see it."""
    groups = _make_groups(1, 2, 3)
    user = _make_user(is_admin=False)

    with patch(
        "bisheng.workstation.domain.services.workstation_service.ToolPermissionService.filter_tool_ids_by_permission_async",
        new=AsyncMock(return_value=["2"]),  # user only has permission for type 2
    ) as mock_filter:
        result = await WorkStationService._afilter_tools_by_view_permission(groups, user)

    assert [g["id"] for g in result] == [2]
    mock_filter.assert_awaited_once()
    args, _ = mock_filter.call_args
    assert args[0] is user
    assert sorted(args[1]) == [1, 2, 3]
    assert args[2] == "view_tool"


@pytest.mark.asyncio
async def test_admin_bypasses_view_permission_filter():
    """Admins see every configured tool regardless of permission bindings."""
    groups = _make_groups(1, 2, 3)
    user = _make_user(is_admin=True)

    with patch(
        "bisheng.workstation.domain.services.workstation_service.ToolPermissionService.filter_tool_ids_by_permission_async",
        new=AsyncMock(return_value=[]),
    ) as mock_filter:
        result = await WorkStationService._afilter_tools_by_view_permission(groups, user)

    # Admin short-circuit must not consult the permission service at all.
    mock_filter.assert_not_called()
    assert sorted(g["id"] for g in result) == [1, 2, 3]


@pytest.mark.asyncio
async def test_no_login_user_keeps_unfiltered_behavior():
    """Without a login_user (legacy/test paths) no filtering is applied."""
    groups = _make_groups(1, 2)

    with patch(
        "bisheng.workstation.domain.services.workstation_service.ToolPermissionService.filter_tool_ids_by_permission_async",
        new=AsyncMock(return_value=[]),
    ) as mock_filter:
        result = await WorkStationService._afilter_tools_by_view_permission(groups, None)

    mock_filter.assert_not_called()
    assert sorted(g["id"] for g in result) == [1, 2]


@pytest.mark.asyncio
async def test_filter_fails_closed_on_permission_probe_error():
    """A failing permission probe hides every tool (fail closed, no leak)."""
    groups = _make_groups(1, 2, 3)
    user = _make_user(is_admin=False)

    with patch(
        "bisheng.workstation.domain.services.workstation_service.ToolPermissionService.filter_tool_ids_by_permission_async",
        new=AsyncMock(side_effect=RuntimeError("OpenFGA down")),
    ):
        result = await WorkStationService._afilter_tools_by_view_permission(groups, user)

    assert result == []


@pytest.mark.asyncio
async def test_empty_tool_list_is_returned_as_is():
    """Empty input short-circuits — no permission probe at all."""
    user = _make_user(is_admin=False)

    with patch(
        "bisheng.workstation.domain.services.workstation_service.ToolPermissionService.filter_tool_ids_by_permission_async",
        new=AsyncMock(return_value=[]),
    ) as mock_filter:
        result = await WorkStationService._afilter_tools_by_view_permission([], user)

    mock_filter.assert_not_called()
    assert result == []


@pytest.mark.asyncio
async def test_groups_with_missing_id_pass_through_dropped():
    """A group without an ``id`` is dropped (it cannot be permission-checked)."""
    groups = [
        {"id": 1, "name": "ok", "is_preset": 0, "description": "", "default_checked": False, "children": []},
        {"id": None, "name": "broken", "is_preset": 0, "description": "", "default_checked": False, "children": []},
    ]
    user = _make_user(is_admin=False)

    with patch(
        "bisheng.workstation.domain.services.workstation_service.ToolPermissionService.filter_tool_ids_by_permission_async",
        new=AsyncMock(return_value=["1"]),
    ):
        result = await WorkStationService._afilter_tools_by_view_permission(groups, user)

    assert [g["id"] for g in result] == [1]
