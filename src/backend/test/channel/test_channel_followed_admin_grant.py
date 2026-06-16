"""Admin users must still see channels they were directly authorized to in the followed list.

PermissionService.list_accessible_ids short-circuits to None ("can read all") for admins,
so get_my_channels(FOLLOWED) — which adds ReBAC-accessible channels for normal users — would
drop channels an admin was specifically granted via member management (direct user grant:
ReBAC + binding, no membership row). The fix recovers those from the admin's direct channel
bindings.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.channel.domain.models.channel import ChannelVisibilityEnum
from bisheng.channel.domain.schemas.channel_manager_schema import (
    MyChannelQueryRequest,
    QueryTypeEnum,
    SortByEnum,
)
from bisheng.channel.domain.services.channel_service import ChannelService

_RP = "bisheng.permission.api.endpoints.resource_permission._get_bindings"


class _Admin:
    user_id = 7
    tenant_id = 1

    def is_admin(self):
        return True


def _service(channel_repository=None, member_repository=None):
    service = ChannelService(
        channel_repository=channel_repository or SimpleNamespace(),
        space_channel_member_repository=member_repository or SimpleNamespace(),
        channel_info_source_repository=SimpleNamespace(),
        article_es_service=SimpleNamespace(count_articles=AsyncMock(return_value=0)),
    )
    # get_my_channels builds a shared ReBAC context (subjects/bindings/models) up front;
    # this test mocks the permission resolution directly, so stub the builder to avoid
    # its DB round-trips in unit scope.
    service._build_channel_permission_context = AsyncMock(return_value={})
    return service


@pytest.mark.asyncio
async def test_directly_granted_channel_ids_extracts_user_channel_bindings():
    service = _service()
    bindings = [
        {"resource_type": "channel", "resource_id": "ch-1", "subject_type": "user", "subject_id": 7},
        {"resource_type": "channel", "resource_id": "ch-2", "subject_type": "department", "subject_id": 3},
        {"resource_type": "knowledge_space", "resource_id": "ks-1", "subject_type": "user", "subject_id": 7},
        {"resource_type": "channel", "resource_id": "ch-3", "subject_type": "user", "subject_id": 99},
    ]
    with patch(_RP, new=AsyncMock(return_value=bindings)):
        ids = await service._directly_granted_channel_ids(7)

    assert ids == ["ch-1"]


@pytest.mark.asyncio
async def test_admin_followed_list_includes_directly_authorized_channel():
    channel = SimpleNamespace(
        id="ch-1",
        name="资讯频道",
        source_list=[],
        visibility=ChannelVisibilityEnum.PUBLIC,
        is_released=True,
        latest_article_update_time=None,
        create_time=None,
        user_id=999,  # not the admin → not a created channel
        is_pinned=False,
    )
    channel_repository = SimpleNamespace(find_channels_by_ids=AsyncMock(return_value=[channel]))
    member_repository = SimpleNamespace(find_channel_memberships=AsyncMock(return_value=[]))
    service = _service(channel_repository, member_repository)
    # Admin has the channel granted (view_channel resolved from the real ReBAC tuple).
    service._get_channel_permission_ids = AsyncMock(return_value={"view_channel"})
    service._calculate_unread_count = AsyncMock(return_value=0)

    bindings = [{"resource_type": "channel", "resource_id": "ch-1", "subject_type": "user", "subject_id": 7}]

    with patch(_RP, new=AsyncMock(return_value=bindings)):
        result = await service.get_my_channels(
            MyChannelQueryRequest(query_type=QueryTypeEnum.FOLLOWED, sort_by=SortByEnum.LATEST_UPDATE),
            _Admin(),
        )

    assert [item.id for item in result] == ["ch-1"]
