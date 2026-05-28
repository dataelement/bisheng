from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.channel.domain.models.channel import ChannelVisibilityEnum
from bisheng.channel.domain.schemas.channel_manager_schema import CreateChannelRequest, UpdateChannelRequest
from bisheng.channel.domain.services.channel_service import ChannelService
from bisheng.common.errcode.channel import ChannelPermissionDeniedError
from bisheng.common.models.space_channel_member import (
    BusinessTypeEnum,
    ChannelRelationEnum,
    MembershipStatusEnum,
    UserRoleEnum,
)


class _LoginUser:
    user_id = 7
    user_name = 'operator'
    tenant_id = 1

    def is_admin(self):
        return False

    async def get_user_groups(self, user_id: int):
        return [{'id': 1, 'name': f'group-{user_id}'}]


def _service(channel_repository, member_repository, article_es_service=None):
    return ChannelService(
        channel_repository=channel_repository,
        space_channel_member_repository=member_repository,
        channel_info_source_repository=SimpleNamespace(find_by_ids=AsyncMock(return_value=[])),
        article_es_service=article_es_service or SimpleNamespace(count_articles=AsyncMock(return_value=0)),
    )


@pytest.mark.asyncio
async def test_create_channel_writes_owner_relation_for_creator():
    channel = SimpleNamespace(
        id='channel-1',
        name='资讯频道',
        source_list=[],
        description='',
        visibility=ChannelVisibilityEnum.PUBLIC,
        filter_rules=[],
        user_id=7,
        is_released=True,
    )
    channel_repository = SimpleNamespace(save=AsyncMock(return_value=channel))
    member_repository = SimpleNamespace(
        find_channel_memberships=AsyncMock(return_value=[]),
        add_member=AsyncMock(),
    )
    service = _service(channel_repository, member_repository)

    with patch(
        'bisheng.channel.domain.services.channel_service.OwnerService.write_owner_tuple',
        new=AsyncMock(),
    ), patch(
        'bisheng.channel.domain.services.channel_service.get_bisheng_information_client',
        new=AsyncMock(return_value=SimpleNamespace(subscribe_information_source=AsyncMock())),
    ):
        await service.create_channel(
            CreateChannelRequest(
                name='资讯频道',
                source_list=[],
                visibility=ChannelVisibilityEnum.PUBLIC,
                is_released=True,
            ),
            _LoginUser(),
        )

    member_repository.add_member.assert_awaited_once_with(
        business_id='channel-1',
        business_type=BusinessTypeEnum.CHANNEL,
        user_id=7,
        role=UserRoleEnum.CREATOR,
        relation=ChannelRelationEnum.OWNER,
        grant_subject_type='self',
        grant_subject_id=7,
        grant_relation=ChannelRelationEnum.OWNER,
        grant_model_id=ChannelRelationEnum.OWNER.value,
        grant_binding_key='channel:channel-1:self:7:owner:-',
    )


@pytest.mark.asyncio
async def test_channel_detail_returns_current_user_relation():
    channel = SimpleNamespace(
        id='channel-1',
        name='资讯频道',
        description='',
        source_list=[],
        visibility=ChannelVisibilityEnum.PUBLIC,
        filter_rules=[],
        is_released=True,
        latest_article_update_time=None,
        create_time=None,
    )
    membership = SimpleNamespace(
        status=MembershipStatusEnum.ACTIVE,
        user_role=UserRoleEnum.ADMIN,
        relation=ChannelRelationEnum.MANAGER,
        update_time=None,
    )
    creator = SimpleNamespace(user_id=1)
    channel_repository = SimpleNamespace(find_channels_by_ids=AsyncMock(return_value=[channel]))
    member_repository = SimpleNamespace(
        find_membership=AsyncMock(return_value=membership),
        find_members_by_role=AsyncMock(return_value=[creator]),
        count_channel_members=AsyncMock(return_value=2),
    )
    service = _service(channel_repository, member_repository)

    with patch(
        'bisheng.channel.domain.services.channel_service.UserDao.aget_user_by_ids',
        new=AsyncMock(return_value=[SimpleNamespace(user_name='creator')]),
    ):
        detail = await service.get_channel_detail('channel-1', _LoginUser())

    assert detail.relation == ChannelRelationEnum.MANAGER


@pytest.mark.asyncio
async def test_channel_member_list_returns_four_level_relation_order():
    current_member = SimpleNamespace(
        status=MembershipStatusEnum.ACTIVE,
        user_role=UserRoleEnum.CREATOR,
        relation=ChannelRelationEnum.OWNER,
    )
    members = [
        SimpleNamespace(user_id=1, user_role=UserRoleEnum.CREATOR, relation=ChannelRelationEnum.OWNER),
        SimpleNamespace(user_id=2, user_role=UserRoleEnum.ADMIN, relation=ChannelRelationEnum.MANAGER),
        SimpleNamespace(user_id=3, user_role=UserRoleEnum.MEMBER, relation=ChannelRelationEnum.EDITOR),
        SimpleNamespace(user_id=4, user_role=UserRoleEnum.MEMBER, relation=ChannelRelationEnum.VIEWER),
    ]
    member_repository = SimpleNamespace(
        find_membership=AsyncMock(return_value=current_member),
        find_channel_members_paginated=AsyncMock(return_value=members),
        count_channel_members=AsyncMock(return_value=4),
    )
    service = _service(SimpleNamespace(), member_repository)
    users = [
        SimpleNamespace(user_id=1, user_name='owner', avatar=None),
        SimpleNamespace(user_id=2, user_name='manager', avatar=None),
        SimpleNamespace(user_id=3, user_name='editor', avatar=None),
        SimpleNamespace(user_id=4, user_name='viewer', avatar=None),
    ]

    with patch(
        'bisheng.channel.domain.services.channel_service.UserDao.aget_user_by_ids',
        new=AsyncMock(return_value=users),
    ), patch(
        'bisheng.user.domain.services.user.UserService.get_avatar_share_link',
        new=AsyncMock(return_value=None),
    ):
        page = await service.list_channel_members('channel-1', 1, 20, None, _LoginUser())

    assert [item.relation for item in page.data] == [
        ChannelRelationEnum.OWNER,
        ChannelRelationEnum.MANAGER,
        ChannelRelationEnum.EDITOR,
        ChannelRelationEnum.VIEWER,
    ]
    assert [item.user_role for item in page.data] == ['creator', 'admin', 'member', 'member']


@pytest.mark.asyncio
async def test_editor_can_update_channel_settings():
    channel = SimpleNamespace(
        id='channel-1',
        name='旧频道',
        description='旧描述',
        source_list=[],
        visibility=ChannelVisibilityEnum.PUBLIC,
        filter_rules=[],
        is_released=True,
    )
    current_member = SimpleNamespace(
        status=MembershipStatusEnum.ACTIVE,
        user_role=UserRoleEnum.MEMBER,
        relation=ChannelRelationEnum.EDITOR,
    )
    channel_repository = SimpleNamespace(
        find_by_id=AsyncMock(return_value=channel),
        update=AsyncMock(side_effect=lambda item: item),
    )
    member_repository = SimpleNamespace(find_membership=AsyncMock(return_value=current_member))
    service = _service(channel_repository, member_repository)

    with patch(
        'bisheng.channel.domain.services.channel_service.get_bisheng_information_client',
        new=AsyncMock(return_value=SimpleNamespace()),
    ):
        result = await service.update_channel(
            'channel-1',
            UpdateChannelRequest(name='新频道', description='新描述'),
            _LoginUser(),
        )

    assert result.name == '新频道'
    assert result.description == '新描述'
    channel_repository.update.assert_awaited_once_with(channel)


@pytest.mark.asyncio
async def test_editor_switch_private_preserves_existing_owner_tuple():
    channel = SimpleNamespace(
        id='channel-1',
        name='频道',
        description='',
        source_list=[],
        visibility=ChannelVisibilityEnum.PUBLIC,
        filter_rules=[],
        is_released=True,
    )
    current_member = SimpleNamespace(
        status=MembershipStatusEnum.ACTIVE,
        user_role=UserRoleEnum.MEMBER,
        relation=ChannelRelationEnum.EDITOR,
    )
    owner = SimpleNamespace(user_id=1)
    channel_repository = SimpleNamespace(
        find_by_id=AsyncMock(return_value=channel),
        update=AsyncMock(side_effect=lambda item: item),
    )
    member_repository = SimpleNamespace(
        find_membership=AsyncMock(return_value=current_member),
        find_members_by_role=AsyncMock(return_value=[owner]),
        remove_non_creator_members=AsyncMock(),
    )
    service = _service(channel_repository, member_repository)

    with patch(
        'bisheng.channel.domain.services.channel_service.OwnerService.delete_resource_tuples',
        new=AsyncMock(),
    ) as mock_delete_tuples, patch(
        'bisheng.channel.domain.services.channel_service.OwnerService.write_owner_tuple',
        new=AsyncMock(),
    ) as mock_write_owner, patch(
        'bisheng.channel.domain.services.channel_service.get_bisheng_information_client',
        new=AsyncMock(return_value=SimpleNamespace()),
    ):
        await service.update_channel(
            'channel-1',
            UpdateChannelRequest(visibility=ChannelVisibilityEnum.PRIVATE),
            _LoginUser(),
        )

    member_repository.find_members_by_role.assert_awaited_once_with('channel-1', UserRoleEnum.CREATOR)
    member_repository.remove_non_creator_members.assert_awaited_once_with('channel-1')
    mock_delete_tuples.assert_awaited_once_with('channel', 'channel-1')
    mock_write_owner.assert_awaited_once_with(1, 'channel', 'channel-1')


@pytest.mark.asyncio
async def test_viewer_cannot_update_channel_settings():
    channel = SimpleNamespace(
        id='channel-1',
        name='旧频道',
        description='旧描述',
        source_list=[],
        visibility=ChannelVisibilityEnum.PUBLIC,
        filter_rules=[],
        is_released=True,
    )
    current_member = SimpleNamespace(
        status=MembershipStatusEnum.ACTIVE,
        user_role=UserRoleEnum.MEMBER,
        relation=ChannelRelationEnum.VIEWER,
    )
    channel_repository = SimpleNamespace(
        find_by_id=AsyncMock(return_value=channel),
        update=AsyncMock(side_effect=lambda item: item),
    )
    member_repository = SimpleNamespace(find_membership=AsyncMock(return_value=current_member))
    service = _service(channel_repository, member_repository)

    with pytest.raises(ChannelPermissionDeniedError):
        await service.update_channel(
            'channel-1',
            UpdateChannelRequest(name='新频道'),
            _LoginUser(),
        )

    channel_repository.update.assert_not_awaited()
