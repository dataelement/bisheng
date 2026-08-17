"""F050 Channel settings save order and PRIVATE permission contracts."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.channel.domain.models.channel import Channel, ChannelVisibilityEnum
from bisheng.channel.domain.schemas.channel_manager_schema import UpdateChannelRequest
from bisheng.channel.domain.services.channel_service import ChannelService

_CS = "bisheng.channel.domain.services.channel_service"


def _channel() -> Channel:
    return Channel(
        id="channel-1",
        name="News",
        source_list=[],
        visibility=ChannelVisibilityEnum.PUBLIC,
        user_id=7,
        tenant_id=3,
    )


def _service(repository, members):
    return ChannelService(
        channel_repository=repository,
        space_channel_member_repository=members,
        channel_info_source_repository=SimpleNamespace(),
    )


async def test_business_save_failure_does_not_touch_grants_or_memberships() -> None:
    repository = SimpleNamespace(
        find_by_id=AsyncMock(return_value=_channel()),
        update=AsyncMock(side_effect=RuntimeError("save failed")),
    )
    members = SimpleNamespace(remove_non_creator_members=AsyncMock())
    service = _service(repository, members)
    adapter_lookup = AsyncMock()
    with (
        patch(f"{_CS}.require_business_action", new=AsyncMock()),
        patch(f"{_CS}.get_bisheng_information_client", new=AsyncMock(return_value=SimpleNamespace())),
        patch(f"{_CS}.get_f048_resource_adapter", new=adapter_lookup),
    ):
        with pytest.raises(RuntimeError, match="save failed"):
            await service.update_channel(
                "channel-1",
                UpdateChannelRequest(visibility=ChannelVisibilityEnum.PRIVATE),
                SimpleNamespace(user_id=7, user_name="creator", tenant_id=3),
            )

    adapter_lookup.assert_not_awaited()
    members.remove_non_creator_members.assert_not_awaited()


async def test_private_projection_commits_before_membership_cleanup() -> None:
    order = []
    channel = _channel()

    async def save(value):
        order.append("business")
        return value

    adapter = SimpleNamespace(
        load_permission_record=AsyncMock(return_value=SimpleNamespace(resource_id="channel-1")),
        remove_ordinary_sources=AsyncMock(side_effect=lambda **_: order.append("permission")),
    )

    async def remove_members(_channel_id):
        order.append("membership")

    repository = SimpleNamespace(find_by_id=AsyncMock(return_value=channel), update=AsyncMock(side_effect=save))
    members = SimpleNamespace(
        find_members_by_role=AsyncMock(return_value=[SimpleNamespace(user_id=7)]),
        remove_non_creator_members=AsyncMock(side_effect=remove_members),
    )
    service = _service(repository, members)
    with (
        patch(f"{_CS}.require_business_action", new=AsyncMock()),
        patch(f"{_CS}.get_bisheng_information_client", new=AsyncMock(return_value=SimpleNamespace())),
        patch(f"{_CS}.get_f048_resource_adapter", new=AsyncMock(return_value=adapter)),
        patch(f"{_CS}.resolve_permission_actor", new=AsyncMock(return_value=SimpleNamespace(user_id=7))),
    ):
        result = await service.update_channel(
            "channel-1",
            UpdateChannelRequest(visibility=ChannelVisibilityEnum.PRIVATE),
            SimpleNamespace(user_id=7, user_name="creator", tenant_id=3),
        )

    assert result.visibility == ChannelVisibilityEnum.PRIVATE
    assert order == ["business", "permission", "membership"]


async def test_private_projection_failure_preserves_membership_rows() -> None:
    repository = SimpleNamespace(
        find_by_id=AsyncMock(return_value=_channel()),
        update=AsyncMock(side_effect=lambda value: value),
    )
    members = SimpleNamespace(
        find_members_by_role=AsyncMock(return_value=[]),
        remove_non_creator_members=AsyncMock(),
    )
    adapter = SimpleNamespace(
        load_permission_record=AsyncMock(return_value=SimpleNamespace(resource_id="channel-1")),
        remove_ordinary_sources=AsyncMock(side_effect=RuntimeError("projection failed")),
    )
    service = _service(repository, members)
    with (
        patch(f"{_CS}.require_business_action", new=AsyncMock()),
        patch(f"{_CS}.get_bisheng_information_client", new=AsyncMock(return_value=SimpleNamespace())),
        patch(f"{_CS}.get_f048_resource_adapter", new=AsyncMock(return_value=adapter)),
        patch(f"{_CS}.resolve_permission_actor", new=AsyncMock(return_value=SimpleNamespace(user_id=7))),
    ):
        with pytest.raises(RuntimeError, match="projection failed"):
            await service.update_channel(
                "channel-1",
                UpdateChannelRequest(visibility=ChannelVisibilityEnum.PRIVATE),
                SimpleNamespace(user_id=7, user_name="creator", tenant_id=3),
            )

    members.remove_non_creator_members.assert_not_awaited()
