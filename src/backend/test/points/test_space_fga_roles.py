"""OpenFGA owner/manager 解析：月奖与 P7 共用。"""

from unittest.mock import AsyncMock, patch

import pytest

from bisheng.points.domain.services.space_fga_roles import (
    SpaceFgaRolesError,
    read_space_owner_manager_ids,
    resolve_space_owner_manager_ids,
)


@pytest.mark.asyncio
async def test_read_space_owner_manager_ids_maps_user_tuples_and_creator_fallback():
    fga = AsyncMock()
    fga.read_tuples = AsyncMock(
        side_effect=[
            [
                {"user": "user:220", "relation": "owner"},
                {"user": "user:1", "relation": "owner"},
                {"user": "department:1#member", "relation": "owner"},
            ],
            [
                {"user": "user:221", "relation": "manager"},
            ],
        ]
    )

    with (
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService._aget_fga",
            AsyncMock(return_value=fga),
        ),
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService._get_resource_creator",
            AsyncMock(return_value=99),
        ),
    ):
        owners, managers = await read_space_owner_manager_ids(19)

    assert owners == {220, 1, 99}
    assert managers == {221}
    assert fga.read_tuples.await_count == 2


@pytest.mark.asyncio
async def test_read_space_owner_manager_ids_raises_when_fga_unavailable():
    with patch(
        "bisheng.permission.domain.services.permission_service.PermissionService._aget_fga",
        AsyncMock(return_value=None),
    ):
        with pytest.raises(SpaceFgaRolesError):
            await read_space_owner_manager_ids(19)


@pytest.mark.asyncio
async def test_resolve_space_owner_manager_ids_unions_roles():
    with patch(
        "bisheng.points.domain.services.space_fga_roles.read_space_owner_manager_ids",
        AsyncMock(return_value=({10, 11}, {11, 12})),
    ):
        got = await resolve_space_owner_manager_ids(19)
    assert got == frozenset({10, 11, 12})


@pytest.mark.asyncio
async def test_resolve_space_owner_manager_ids_fga_fail_uses_creator_only():
    with (
        patch(
            "bisheng.points.domain.services.space_fga_roles.read_space_owner_manager_ids",
            AsyncMock(side_effect=SpaceFgaRolesError("down")),
        ),
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService._get_resource_creator",
            AsyncMock(return_value=7),
        ),
    ):
        got = await resolve_space_owner_manager_ids(19)
    assert got == frozenset({7})
