from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.channel.domain.models.channel import ChannelVisibilityEnum
from bisheng.channel.domain.schemas.channel_manager_schema import (
    CreateChannelRequest,
    MyChannelQueryRequest,
    QueryTypeEnum,
    SortByEnum,
    UpdateChannelRequest,
)
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
    user_name = "operator"
    tenant_id = 1

    def is_admin(self):
        return False

    async def get_user_groups(self, user_id: int):
        return [{"id": 1, "name": f"group-{user_id}"}]


def _service(channel_repository, member_repository, article_es_service=None):
    service = ChannelService(
        channel_repository=channel_repository,
        space_channel_member_repository=member_repository,
        channel_info_source_repository=SimpleNamespace(find_by_ids=AsyncMock(return_value=[])),
        article_es_service=article_es_service
        or SimpleNamespace(
            count_articles=AsyncMock(return_value=0),
            count_articles_batch=AsyncMock(side_effect=lambda requests: [0] * len(requests)),
        ),
    )
    # get_my_channels builds a shared ReBAC context (subjects/bindings/models) up front;
    # these tests mock get_effective_permission_ids_async directly, so the context content
    # is irrelevant — stub the builder to avoid its DB round-trips in unit scope.
    service._build_channel_permission_context = AsyncMock(return_value={})
    return service


@pytest.mark.asyncio
async def test_create_channel_writes_owner_relation_for_creator():
    channel = SimpleNamespace(
        id="channel-1",
        name="资讯频道",
        source_list=[],
        description="",
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

    with (
        patch(
            "bisheng.channel.domain.services.channel_service.QuotaService.get_effective_quota",
            new=AsyncMock(return_value=-1),
        ),
        patch(
            "bisheng.channel.domain.services.channel_service.OwnerService.write_owner_tuple",
            new=AsyncMock(),
        ),
        patch(
            "bisheng.channel.domain.services.channel_service.get_bisheng_information_client",
            new=AsyncMock(return_value=SimpleNamespace(subscribe_information_source=AsyncMock())),
        ),
    ):
        await service.create_channel(
            CreateChannelRequest(
                name="资讯频道",
                source_list=[],
                visibility=ChannelVisibilityEnum.PUBLIC,
                is_released=True,
            ),
            _LoginUser(),
        )

    member_repository.add_member.assert_awaited_once_with(
        business_id="channel-1",
        business_type=BusinessTypeEnum.CHANNEL,
        user_id=7,
        role=UserRoleEnum.CREATOR,
        relation=ChannelRelationEnum.OWNER,
        grant_subject_type="self",
        grant_subject_id=7,
        grant_relation=ChannelRelationEnum.OWNER,
        grant_model_id=ChannelRelationEnum.OWNER.value,
        grant_binding_key="channel:channel-1:self:7:owner:-",
    )


@pytest.mark.asyncio
async def test_channel_detail_returns_current_user_relation():
    channel = SimpleNamespace(
        id="channel-1",
        name="资讯频道",
        description="",
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
        "bisheng.channel.domain.services.channel_service.UserDao.aget_user_by_ids",
        new=AsyncMock(return_value=[SimpleNamespace(user_name="creator")]),
    ):
        detail = await service.get_channel_detail("channel-1", _LoginUser())

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
        SimpleNamespace(user_id=1, user_name="owner", avatar=None),
        SimpleNamespace(user_id=2, user_name="manager", avatar=None),
        SimpleNamespace(user_id=3, user_name="editor", avatar=None),
        SimpleNamespace(user_id=4, user_name="viewer", avatar=None),
    ]

    with (
        patch(
            "bisheng.channel.domain.services.channel_service.UserDao.aget_user_by_ids",
            new=AsyncMock(return_value=users),
        ),
        patch(
            "bisheng.user.domain.services.user.UserService.get_avatar_share_link",
            new=AsyncMock(return_value=None),
        ),
    ):
        page = await service.list_channel_members("channel-1", 1, 20, None, _LoginUser())

    assert [item.relation for item in page.data] == [
        ChannelRelationEnum.OWNER,
        ChannelRelationEnum.MANAGER,
        ChannelRelationEnum.EDITOR,
        ChannelRelationEnum.VIEWER,
    ]
    assert [item.user_role for item in page.data] == ["creator", "admin", "member", "member"]


@pytest.mark.asyncio
async def test_editor_can_update_channel_settings():
    channel = SimpleNamespace(
        id="channel-1",
        name="旧频道",
        description="旧描述",
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
        "bisheng.channel.domain.services.channel_service.get_bisheng_information_client",
        new=AsyncMock(return_value=SimpleNamespace()),
    ):
        result = await service.update_channel(
            "channel-1",
            UpdateChannelRequest(name="新频道", description="新描述"),
            _LoginUser(),
        )

    assert result.name == "新频道"
    assert result.description == "新描述"
    channel_repository.update.assert_awaited_once_with(channel)


@pytest.mark.asyncio
async def test_followed_channels_include_private_authorized_user_channel():
    channel = SimpleNamespace(
        id="channel-1",
        name="私有频道",
        source_list=[],
        visibility=ChannelVisibilityEnum.PRIVATE,
        filter_rules=[],
        is_released=True,
        latest_article_update_time=None,
        create_time=None,
    )
    membership = SimpleNamespace(
        business_id="channel-1",
        status=MembershipStatusEnum.ACTIVE,
        user_role=UserRoleEnum.MEMBER,
        relation=ChannelRelationEnum.EDITOR,
        grant_subject_type="user",
        grant_subject_id=7,
        grant_binding_key="channel:channel-1:user:7:editor:-",
        is_pinned=False,
        create_time=None,
    )
    channel_repository = SimpleNamespace(find_channels_by_ids=AsyncMock(return_value=[channel]))
    member_repository = SimpleNamespace(find_channel_memberships=AsyncMock(return_value=[membership]))
    service = _service(channel_repository, member_repository)

    with (
        patch(
            "bisheng.channel.domain.services.channel_service.PermissionService.list_accessible_ids",
            new=AsyncMock(return_value=["channel-1"]),
        ),
        patch(
            "bisheng.permission.domain.services.fine_grained_permission_service.FineGrainedPermissionService.get_effective_permission_ids_async",
            new=AsyncMock(return_value={"view_channel", "edit_channel"}),
        ),
    ):
        channels = await service.get_my_channels(
            MyChannelQueryRequest(
                query_type=QueryTypeEnum.FOLLOWED,
                sort_by=SortByEnum.LATEST_UPDATE,
            ),
            _LoginUser(),
        )

    assert [item.id for item in channels] == ["channel-1"]
    assert channels[0].relation == ChannelRelationEnum.EDITOR.value
    assert channels[0].user_role == UserRoleEnum.MEMBER.value


@pytest.mark.asyncio
async def test_followed_channels_include_rebac_channel_without_membership():
    channel = SimpleNamespace(
        id="channel-3",
        name="授权频道",
        source_list=[],
        visibility=ChannelVisibilityEnum.PRIVATE,
        filter_rules=[],
        is_released=True,
        latest_article_update_time=None,
        create_time=None,
        user_id=99,
    )
    channel_repository = SimpleNamespace(find_channels_by_ids=AsyncMock(return_value=[channel]))
    member_repository = SimpleNamespace(find_channel_memberships=AsyncMock(return_value=[]))
    service = _service(channel_repository, member_repository)

    with (
        patch(
            "bisheng.channel.domain.services.channel_service.PermissionService.list_accessible_ids",
            new=AsyncMock(return_value=["channel-3"]),
        ),
        patch(
            "bisheng.permission.domain.services.fine_grained_permission_service.FineGrainedPermissionService.get_effective_permission_ids_async",
            new=AsyncMock(return_value={"view_channel", "edit_channel"}),
        ),
    ):
        channels = await service.get_my_channels(
            MyChannelQueryRequest(
                query_type=QueryTypeEnum.FOLLOWED,
                sort_by=SortByEnum.LATEST_UPDATE,
            ),
            _LoginUser(),
        )

    assert [item.id for item in channels] == ["channel-3"]
    assert channels[0].permission_ids == ["edit_channel", "view_channel"]
    assert channels[0].relation == ChannelRelationEnum.EDITOR.value


@pytest.mark.asyncio
async def test_authorized_membership_does_not_override_relation_model_permissions():
    channel = SimpleNamespace(
        id="channel-4",
        name="历史授权频道",
        source_list=[],
        visibility=ChannelVisibilityEnum.PRIVATE,
        filter_rules=[],
        is_released=True,
        latest_article_update_time=None,
        create_time=None,
        user_id=99,
    )
    membership = SimpleNamespace(
        business_id="channel-4",
        status=MembershipStatusEnum.ACTIVE,
        user_role=UserRoleEnum.ADMIN,
        relation=ChannelRelationEnum.MANAGER,
        grant_subject_type="user",
        grant_subject_id=7,
        grant_binding_key="channel:channel-4:user:7:manager:-",
        is_pinned=False,
        create_time=None,
    )
    channel_repository = SimpleNamespace(find_channels_by_ids=AsyncMock(return_value=[channel]))
    member_repository = SimpleNamespace(find_channel_memberships=AsyncMock(return_value=[membership]))
    service = _service(channel_repository, member_repository)

    with (
        patch(
            "bisheng.channel.domain.services.channel_service.PermissionService.list_accessible_ids",
            new=AsyncMock(return_value=["channel-4"]),
        ),
        patch(
            "bisheng.permission.domain.services.fine_grained_permission_service.FineGrainedPermissionService.get_effective_permission_ids_async",
            new=AsyncMock(return_value={"view_channel"}),
        ),
    ):
        channels = await service.get_my_channels(
            MyChannelQueryRequest(
                query_type=QueryTypeEnum.FOLLOWED,
                sort_by=SortByEnum.LATEST_UPDATE,
            ),
            _LoginUser(),
        )

    assert [item.id for item in channels] == ["channel-4"]
    assert channels[0].permission_ids == ["view_channel"]
    assert channels[0].relation == ChannelRelationEnum.VIEWER.value


@pytest.mark.asyncio
async def test_followed_channels_include_private_organization_grant_channel():
    channel = SimpleNamespace(
        id="channel-2",
        name="组织授权私有频道",
        source_list=[],
        visibility=ChannelVisibilityEnum.PRIVATE,
        filter_rules=[],
        is_released=True,
        latest_article_update_time=None,
        create_time=None,
    )
    membership = SimpleNamespace(
        business_id="channel-2",
        status=MembershipStatusEnum.ACTIVE,
        user_role=UserRoleEnum.MEMBER,
        relation=ChannelRelationEnum.VIEWER,
        grant_subject_type="user_group",
        grant_subject_id=12,
        grant_binding_key="channel:channel-2:user_group:12:viewer:-",
        is_pinned=False,
        create_time=None,
    )
    channel_repository = SimpleNamespace(find_channels_by_ids=AsyncMock(return_value=[channel]))
    member_repository = SimpleNamespace(find_channel_memberships=AsyncMock(return_value=[membership]))
    service = _service(channel_repository, member_repository)

    with (
        patch(
            "bisheng.channel.domain.services.channel_service.PermissionService.list_accessible_ids",
            new=AsyncMock(return_value=["channel-2"]),
        ),
        patch(
            "bisheng.permission.domain.services.fine_grained_permission_service.FineGrainedPermissionService.get_effective_permission_ids_async",
            new=AsyncMock(return_value={"view_channel"}),
        ),
    ):
        channels = await service.get_my_channels(
            MyChannelQueryRequest(
                query_type=QueryTypeEnum.FOLLOWED,
                sort_by=SortByEnum.LATEST_UPDATE,
            ),
            _LoginUser(),
        )

    assert [item.id for item in channels] == ["channel-2"]
    assert channels[0].relation == ChannelRelationEnum.VIEWER.value


@pytest.mark.asyncio
async def test_switch_private_revokes_all_non_owner_relations():
    channel = SimpleNamespace(
        id="channel-1",
        name="频道",
        description="",
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
        remove_non_creator_members=AsyncMock(return_value=None),
    )
    service = _service(channel_repository, member_repository)

    with (
        patch(
            "bisheng.channel.domain.services.channel_service.OwnerService.delete_non_owner_resource_tuples",
            new=AsyncMock(return_value=3),
        ) as mock_delete_non_owner,
        patch(
            "bisheng.channel.domain.services.channel_service.OwnerService.write_owner_tuple",
            new=AsyncMock(),
        ) as mock_write_owner,
        patch(
            "bisheng.channel.domain.services.channel_authorization_service.ChannelAuthorizationService.clear_non_owner_bindings",
            new=AsyncMock(return_value=2),
        ) as mock_clear_bindings,
        patch(
            "bisheng.channel.domain.services.channel_service.get_bisheng_information_client",
            new=AsyncMock(return_value=SimpleNamespace()),
        ),
    ):
        await service.update_channel(
            "channel-1",
            UpdateChannelRequest(visibility=ChannelVisibilityEnum.PRIVATE),
            _LoginUser(),
        )

    member_repository.find_members_by_role.assert_awaited_once_with("channel-1", UserRoleEnum.CREATOR)
    member_repository.remove_non_creator_members.assert_awaited_once_with("channel-1")
    mock_delete_non_owner.assert_awaited_once_with("channel", "channel-1")
    mock_clear_bindings.assert_awaited_once_with("channel-1")
    mock_write_owner.assert_awaited_once_with(1, "channel", "channel-1")


@pytest.mark.asyncio
async def test_switch_review_to_private_revokes_all_non_owner_relations():
    channel = SimpleNamespace(
        id="channel-1",
        name="频道",
        description="",
        source_list=[],
        visibility=ChannelVisibilityEnum.REVIEW,
        filter_rules=[],
        is_released=True,
    )
    current_member = SimpleNamespace(
        status=MembershipStatusEnum.ACTIVE,
        user_role=UserRoleEnum.CREATOR,
        relation=ChannelRelationEnum.OWNER,
    )
    owner = SimpleNamespace(user_id=1)
    channel_repository = SimpleNamespace(
        find_by_id=AsyncMock(return_value=channel),
        update=AsyncMock(side_effect=lambda item: item),
    )
    member_repository = SimpleNamespace(
        find_membership=AsyncMock(return_value=current_member),
        find_members_by_role=AsyncMock(return_value=[owner]),
        remove_non_creator_members=AsyncMock(return_value=None),
    )
    service = _service(channel_repository, member_repository)

    with (
        patch(
            "bisheng.channel.domain.services.channel_service.OwnerService.delete_non_owner_resource_tuples",
            new=AsyncMock(return_value=1),
        ) as mock_delete_non_owner,
        patch(
            "bisheng.channel.domain.services.channel_service.OwnerService.write_owner_tuple",
            new=AsyncMock(),
        ),
        patch(
            "bisheng.channel.domain.services.channel_authorization_service.ChannelAuthorizationService.clear_non_owner_bindings",
            new=AsyncMock(return_value=0),
        ) as mock_clear_bindings,
        patch(
            "bisheng.channel.domain.services.channel_service.get_bisheng_information_client",
            new=AsyncMock(return_value=SimpleNamespace()),
        ),
    ):
        await service.update_channel(
            "channel-1",
            UpdateChannelRequest(visibility=ChannelVisibilityEnum.PRIVATE),
            _LoginUser(),
        )

    member_repository.remove_non_creator_members.assert_awaited_once_with("channel-1")
    mock_delete_non_owner.assert_awaited_once_with("channel", "channel-1")
    mock_clear_bindings.assert_awaited_once_with("channel-1")


@pytest.mark.asyncio
async def test_viewer_cannot_update_channel_settings():
    channel = SimpleNamespace(
        id="channel-1",
        name="旧频道",
        description="旧描述",
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
            "channel-1",
            UpdateChannelRequest(name="新频道"),
            _LoginUser(),
        )

    channel_repository.update.assert_not_awaited()
