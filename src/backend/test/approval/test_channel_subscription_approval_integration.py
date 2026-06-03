from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_review_channel_subscription_uses_approval_gate_pending():
    from bisheng.channel.domain.models.channel import ChannelVisibilityEnum
    from bisheng.channel.domain.schemas.channel_manager_schema import (
        SubscribeChannelRequest,
        SubscriptionStatusEnum,
    )
    from bisheng.channel.domain.services.channel_service import ChannelService
    from bisheng.common.models.space_channel_member import (
        BusinessTypeEnum,
        MembershipStatusEnum,
        UserRoleEnum,
    )

    channel = SimpleNamespace(id='channel-1', name='资讯频道', visibility=ChannelVisibilityEnum.REVIEW)
    channel_repository = SimpleNamespace(find_channels_by_ids=AsyncMock(return_value=[channel]))
    member_repository = SimpleNamespace(
        find_membership=AsyncMock(return_value=None),
        add_member=AsyncMock(),
        update=AsyncMock(),
    )
    approval_gate = SimpleNamespace(
        request_or_pass=AsyncMock(return_value=SimpleNamespace(decision='pending', instance_id=11, task_ids=[]))
    )
    message_service = SimpleNamespace(send_generic_approval=AsyncMock())
    service = ChannelService(
        channel_repository=channel_repository,
        space_channel_member_repository=member_repository,
        channel_info_source_repository=SimpleNamespace(),
        message_service=message_service,
        approval_gate=approval_gate,
    )
    login_user = SimpleNamespace(user_id=42, user_name='alice', tenant_id=7, is_admin=lambda: False)

    with patch(
        'bisheng.channel.domain.services.channel_service.QuotaService.check_quota',
        new=AsyncMock(return_value=True),
    ), patch(
        'bisheng.database.models.department.UserDepartmentDao.aget_user_primary_department',
        new=AsyncMock(return_value=None),
    ):
        status = await service.subscribe_channel(
            SubscribeChannelRequest(channel_id='channel-1'),
            login_user,
        )

    assert status == SubscriptionStatusEnum.PENDING
    member_repository.add_member.assert_awaited_once_with(
        business_id='channel-1',
        business_type=BusinessTypeEnum.CHANNEL,
        user_id=42,
        role=UserRoleEnum.MEMBER,
        status=MembershipStatusEnum.PENDING,
    )
    approval_gate.request_or_pass.assert_awaited_once()
    message_service.send_generic_approval.assert_not_awaited()


@pytest.mark.asyncio
async def test_review_channel_subscription_direct_pass_activates_membership():
    from bisheng.channel.domain.models.channel import ChannelVisibilityEnum
    from bisheng.channel.domain.schemas.channel_manager_schema import (
        SubscribeChannelRequest,
        SubscriptionStatusEnum,
    )
    from bisheng.channel.domain.services.channel_service import ChannelService
    from bisheng.common.models.space_channel_member import MembershipStatusEnum, UserRoleEnum

    channel = SimpleNamespace(id='channel-1', name='资讯频道', visibility=ChannelVisibilityEnum.REVIEW)
    membership = SimpleNamespace(id=99, status=MembershipStatusEnum.REJECTED, user_role='member')
    channel_repository = SimpleNamespace(find_channels_by_ids=AsyncMock(return_value=[channel]))
    member_repository = SimpleNamespace(
        find_membership=AsyncMock(return_value=membership),
        add_member=AsyncMock(),
        update=AsyncMock(),
    )
    approval_gate = SimpleNamespace(
        request_or_pass=AsyncMock(return_value=SimpleNamespace(decision='pass', instance_id=12))
    )
    service = ChannelService(
        channel_repository=channel_repository,
        space_channel_member_repository=member_repository,
        channel_info_source_repository=SimpleNamespace(),
        message_service=SimpleNamespace(send_generic_approval=AsyncMock()),
        approval_gate=approval_gate,
    )
    login_user = SimpleNamespace(user_id=42, user_name='alice', tenant_id=7, is_admin=lambda: False)

    with patch(
        'bisheng.channel.domain.services.channel_service.QuotaService.check_quota',
        new=AsyncMock(return_value=True),
    ), patch(
        'bisheng.database.models.department.UserDepartmentDao.aget_user_primary_department',
        new=AsyncMock(return_value=None),
    ), patch.object(
        ChannelService,
        'sync_direct_channel_user_permissions',
        new_callable=AsyncMock,
    ) as mock_sync_permissions:
        status = await service.subscribe_channel(
            SubscribeChannelRequest(channel_id='channel-1'),
            login_user,
        )

    assert status == SubscriptionStatusEnum.SUBSCRIBED
    assert membership.status == MembershipStatusEnum.ACTIVE
    member_repository.update.assert_awaited()
    mock_sync_permissions.assert_awaited_once_with(
        'channel-1',
        42,
        UserRoleEnum.MEMBER,
        is_active=True,
    )


@pytest.mark.asyncio
async def test_channel_subscribe_scenario_handler_updates_membership_states():
    from bisheng.approval.domain.services.channel_subscribe_scenario_handler import (
        ChannelSubscribeScenarioHandler,
    )
    from bisheng.common.models.space_channel_member import MembershipStatusEnum, UserRoleEnum

    membership = SimpleNamespace(id=1, status=MembershipStatusEnum.PENDING, user_id=42, user_role=UserRoleEnum.MEMBER)
    member_repository = SimpleNamespace(
        find_membership=AsyncMock(return_value=membership),
        update=AsyncMock(side_effect=lambda row: row),
    )
    sync_permissions = AsyncMock()
    handler = ChannelSubscribeScenarioHandler(
        space_channel_member_repository=member_repository,
        sync_permissions=sync_permissions,
    )

    payload = {'channel_id': 'channel-1', 'applicant_user_id': 42}
    await handler.on_approved(instance_id=1, payload_snapshot=payload)
    assert membership.status == MembershipStatusEnum.ACTIVE
    # Approval must mirror the membership into an explicit ReBAC grant.
    sync_permissions.assert_awaited_once_with(
        'channel-1',
        42,
        UserRoleEnum.MEMBER,
        is_active=True,
    )

    membership.status = MembershipStatusEnum.PENDING
    await handler.on_rejected(instance_id=1, payload_snapshot=payload, reason='reject')
    assert membership.status == MembershipStatusEnum.REJECTED
