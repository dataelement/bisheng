"""Subscription presentation and activation use effective F048 access."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import bisheng.channel.domain.services.channel_service as mod
from bisheng.approval.domain.services.channel_subscribe_scenario_handler import ChannelSubscribeScenarioHandler
from bisheng.channel.domain.models.channel import ChannelVisibilityEnum
from bisheng.channel.domain.schemas.channel_manager_schema import SubscribeChannelRequest
from bisheng.channel.domain.services.channel_service import ChannelService
from bisheng.common.models.space_channel_member import MembershipStatusEnum, UserRoleEnum


@pytest.mark.parametrize(
    "status,visible,expected",
    [
        (MembershipStatusEnum.ACTIVE, True, "subscribed"),
        (MembershipStatusEnum.ACTIVE, False, "not_subscribed"),
        (MembershipStatusEnum.PENDING, False, "pending"),
        (MembershipStatusEnum.PENDING, True, "subscribed"),
        (MembershipStatusEnum.REJECTED, False, "rejected"),
        (MembershipStatusEnum.REJECTED, True, "subscribed"),
        (None, True, "subscribed"),
        (None, False, "not_subscribed"),
    ],
)
async def test_detail_square_and_followed_share_effective_access(monkeypatch, status, visible, expected):
    now = datetime.now()
    channel = SimpleNamespace(
        id="channel-1",
        name="News",
        description="",
        user_id=9,
        source_list=[],
        visibility=ChannelVisibilityEnum.REVIEW,
        filter_rules=[],
        is_released=True,
        create_time=now,
        update_time=now,
        latest_article_update_time=None,
    )
    membership = (
        SimpleNamespace(
            status=status,
            update_time=now,
            user_id=42,
            user_role=UserRoleEnum.MEMBER,
        )
        if status
        else None
    )
    members = SimpleNamespace(
        find_membership_split=AsyncMock(return_value=(None, membership)),
        find_members_by_role=AsyncMock(return_value=[]),
        count_channel_members=AsyncMock(return_value=1),
        find_channel_memberships=AsyncMock(return_value=[]),
    )
    service = ChannelService(
        channel_repository=SimpleNamespace(
            find_channels_by_ids=AsyncMock(return_value=[channel]),
            find_followed_by_visible_ids=AsyncMock(return_value=[channel]),
        ),
        space_channel_member_repository=members,
        channel_info_source_repository=SimpleNamespace(),
    )
    service._get_channel_actions = AsyncMock(return_value={"visible"} if visible else set())
    monkeypatch.setattr(mod.ArticleCountCache, "get_main_count", AsyncMock(return_value=22))
    monkeypatch.setattr(mod.ArticleCountCache, "get_main_counts", AsyncMock(return_value={channel.id: 22}))
    monkeypatch.setattr(mod.ArticleCountCache, "set_main_counts", AsyncMock())
    monkeypatch.setattr(mod, "batch_check_business_visible", AsyncMock(return_value={channel.id: visible}))
    monkeypatch.setattr(mod, "resolve_permission_actor", AsyncMock(return_value=SimpleNamespace(current_tenant_id=7)))
    runtime = SimpleNamespace(
        list_visible_objects=AsyncMock(
            return_value=SimpleNamespace(object_ids=[channel.id] if visible else []),
        )
    )
    monkeypatch.setattr(mod, "get_f048_runtime", AsyncMock(return_value=runtime))
    user = SimpleNamespace(user_id=42, tenant_id=7)

    detail = await service.get_channel_detail(channel.id, user)
    square = await service._build_square_items([(channel, status, now, 1)], user)
    followed = await service._get_followed_channels(user, set())

    assert detail.subscription_status == square[0].subscription_status == expected
    assert ("visible" in detail.actions) == visible
    assert [item.id for item in followed] == ([channel.id] if visible else [])


async def test_approval_permission_failure_keeps_pending_and_retry_activates():
    member = SimpleNamespace(id=1, status=MembershipStatusEnum.PENDING, user_id=42, user_role=UserRoleEnum.MEMBER)
    persisted = []
    repo = SimpleNamespace(
        find_membership=AsyncMock(return_value=member),
        update=AsyncMock(side_effect=lambda row: persisted.append(row.status)),
    )
    sync = AsyncMock(side_effect=[RuntimeError("permission unavailable"), None])
    handler = ChannelSubscribeScenarioHandler(repo, sync_permissions=sync)
    payload = {"channel_id": "channel-1", "applicant_user_id": 42}
    with pytest.raises(RuntimeError, match="permission unavailable"):
        await handler.on_approved(1, payload)
    assert member.status == MembershipStatusEnum.PENDING
    assert persisted == []
    await handler.on_approved(1, payload)
    assert persisted == [MembershipStatusEnum.ACTIVE]
    assert sync.await_count == 2


async def test_approval_requires_permission_synchronizer():
    member = SimpleNamespace(id=1, status=MembershipStatusEnum.PENDING, user_id=42, user_role=UserRoleEnum.MEMBER)
    repo = SimpleNamespace(find_membership=AsyncMock(return_value=member), update=AsyncMock())
    with pytest.raises(RuntimeError, match="permission synchronizer"):
        await ChannelSubscribeScenarioHandler(repo).on_approved(1, {"channel_id": "channel-1", "applicant_user_id": 42})
    assert member.status == MembershipStatusEnum.PENDING
    repo.update.assert_not_awaited()


@pytest.mark.parametrize("visibility", [ChannelVisibilityEnum.PUBLIC, ChannelVisibilityEnum.REVIEW])
async def test_stale_active_member_can_resubscribe_with_current_approval_rules(monkeypatch, visibility):
    member = SimpleNamespace(id=1, status=MembershipStatusEnum.ACTIVE, user_id=42, user_role=UserRoleEnum.MEMBER)
    states = []
    repo = SimpleNamespace(
        find_membership=AsyncMock(return_value=member),
        update=AsyncMock(side_effect=lambda row: states.append(row.status)),
    )
    gate = SimpleNamespace(request_or_pass=AsyncMock(return_value=SimpleNamespace(decision="pending", task_ids=[])))
    service = ChannelService(
        channel_repository=SimpleNamespace(
            find_channels_by_ids=AsyncMock(
                return_value=[SimpleNamespace(id="channel-1", name="News", visibility=visibility)]
            )
        ),
        space_channel_member_repository=repo,
        channel_info_source_repository=SimpleNamespace(),
        approval_gate=gate,
    )
    service._get_channel_actions = AsyncMock(return_value=set())
    sync = AsyncMock()
    monkeypatch.setattr(ChannelService, "sync_direct_channel_user_permissions", sync)
    monkeypatch.setattr(
        "bisheng.database.models.department.UserDepartmentDao.aget_user_primary_department",
        AsyncMock(return_value=None),
    )
    result = await service.subscribe_channel(
        SubscribeChannelRequest(channel_id="channel-1"), SimpleNamespace(user_id=42, tenant_id=7)
    )
    if visibility == ChannelVisibilityEnum.PUBLIC:
        assert result == "subscribed"
        assert states == [MembershipStatusEnum.PENDING, MembershipStatusEnum.ACTIVE]
        sync.assert_awaited_once()
    else:
        assert result == "pending"
        assert states == [MembershipStatusEnum.PENDING]
        gate.request_or_pass.assert_awaited_once()
        sync.assert_not_awaited()


async def test_public_subscribe_failure_preserves_retryable_progress(monkeypatch):
    member = SimpleNamespace(id=1, status=MembershipStatusEnum.PENDING, user_id=42, user_role=UserRoleEnum.MEMBER)
    states = []
    service = ChannelService(
        channel_repository=SimpleNamespace(
            find_channels_by_ids=AsyncMock(
                return_value=[SimpleNamespace(id="channel-1", visibility=ChannelVisibilityEnum.PUBLIC)]
            )
        ),
        space_channel_member_repository=SimpleNamespace(
            find_membership=AsyncMock(return_value=member),
            update=AsyncMock(side_effect=lambda row: states.append(row.status)),
        ),
        channel_info_source_repository=SimpleNamespace(),
    )
    service._get_channel_actions = AsyncMock(return_value=set())
    monkeypatch.setattr(
        ChannelService,
        "sync_direct_channel_user_permissions",
        AsyncMock(side_effect=RuntimeError("permission unavailable")),
    )
    with pytest.raises(RuntimeError, match="permission unavailable"):
        await service.subscribe_channel(
            SubscribeChannelRequest(channel_id="channel-1"), SimpleNamespace(user_id=42, tenant_id=7)
        )
    assert states == [MembershipStatusEnum.PENDING]
    assert (
        service._resolve_effective_subscription_status(
            can_read=False, approval_required=False, membership_status=member.status
        )
        == "not_subscribed"
    )


async def test_legacy_approval_failure_keeps_pending(monkeypatch):
    from bisheng.channel.domain.services.channel_subscribe_approval_handler import ChannelSubscribeApprovalHandler

    member = SimpleNamespace(id=1, status=MembershipStatusEnum.PENDING, user_id=42, user_role=UserRoleEnum.MEMBER)
    repo = SimpleNamespace(find_membership=AsyncMock(return_value=member), update=AsyncMock())
    handler = ChannelSubscribeApprovalHandler(
        repo, SimpleNamespace(find_by_id=AsyncMock(return_value=SimpleNamespace(id="channel-1"))), AsyncMock()
    )
    monkeypatch.setattr(handler, "_extract_business_id", lambda *_: "channel-1")
    monkeypatch.setattr(handler, "_extract_applicant_user_id", lambda *_: 42)
    monkeypatch.setattr(
        ChannelService,
        "sync_direct_channel_user_permissions",
        AsyncMock(side_effect=RuntimeError("permission unavailable")),
    )
    with pytest.raises(RuntimeError, match="permission unavailable"):
        await handler.on_approved(SimpleNamespace(id=1, content=[]), 9)
    assert member.status == MembershipStatusEnum.PENDING
    repo.update.assert_not_awaited()


async def test_public_transition_activates_each_member_after_grant(monkeypatch):
    member = SimpleNamespace(id=1, status=MembershipStatusEnum.PENDING, user_id=42, user_role=UserRoleEnum.MEMBER)
    order = []

    async def grant(*_args, **_kwargs):
        assert member.status == MembershipStatusEnum.PENDING
        order.append("permission")

    repo = SimpleNamespace(
        find_all=AsyncMock(return_value=[member]),
        update=AsyncMock(side_effect=lambda _: order.append("membership")),
        remove_rejected_members=AsyncMock(),
    )
    service = ChannelService(
        channel_repository=SimpleNamespace(),
        space_channel_member_repository=repo,
        channel_info_source_repository=SimpleNamespace(),
    )
    monkeypatch.setattr(ChannelService, "sync_direct_channel_user_permissions", grant)
    await service._apply_channel_visibility_transition(
        SimpleNamespace(id="channel-1"),
        old_visibility=ChannelVisibilityEnum.REVIEW,
        new_visibility=ChannelVisibilityEnum.PUBLIC,
        login_user=SimpleNamespace(user_id=9),
    )
    assert order == ["permission", "membership"]
    assert member.status == MembershipStatusEnum.ACTIVE


async def test_subscription_preserves_a_restricted_administrator_role(monkeypatch):
    from bisheng.common.errcode.channel import ChannelAccessDeniedError

    member = SimpleNamespace(status=MembershipStatusEnum.ACTIVE, user_role=UserRoleEnum.ADMIN)
    repo = SimpleNamespace(find_membership=AsyncMock(return_value=member), update=AsyncMock())
    service = ChannelService(
        channel_repository=SimpleNamespace(
            find_channels_by_ids=AsyncMock(
                return_value=[SimpleNamespace(id="channel-1", visibility=ChannelVisibilityEnum.PUBLIC)]
            )
        ),
        space_channel_member_repository=repo,
        channel_info_source_repository=SimpleNamespace(),
    )
    service._get_channel_actions = AsyncMock(return_value={"manage_permission"})
    with pytest.raises(ChannelAccessDeniedError):
        await service.subscribe_channel(
            SubscribeChannelRequest(channel_id="channel-1"), SimpleNamespace(user_id=42, tenant_id=7)
        )
    assert member.user_role == UserRoleEnum.ADMIN
    repo.update.assert_not_awaited()
