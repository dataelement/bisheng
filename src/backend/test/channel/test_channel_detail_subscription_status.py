"""Regression: channel detail must surface PENDING/REJECTED subscription status.

The subscribe button on the channel detail drawer read "subscribe" for a user
who had already applied to a REVIEW channel, while the channel square correctly
showed "applying". Root cause: ``get_channel_detail`` resolved
``subscription_status`` from the ACTIVE-only ``current_membership`` (that lookup
intentionally hides PENDING rows so they can't leak channel permissions), so a
pending application looked like "not subscribed".

The fix keeps the ACTIVE-only membership for permission gating but falls back to
an ``include_inactive`` lookup purely for the displayed subscription status,
mirroring how the channel square resolves it. These tests lock that behaviour.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from bisheng.channel.domain.models.channel import ChannelVisibilityEnum
from bisheng.channel.domain.schemas.channel_manager_schema import SubscriptionStatusEnum
from bisheng.channel.domain.services.channel_service import ChannelService
from bisheng.common.models.space_channel_member import (
    BusinessTypeEnum,
    ChannelRelationEnum,
    MembershipStatusEnum,
    SpaceChannelMember,
    UserRoleEnum,
)
from bisheng.permission.domain.services.fine_grained_permission_service import (
    FineGrainedPermissionService,
)


class _MembershipRepo:
    """``find_membership`` mirrors the real ACTIVE-only default: it only returns
    the (possibly non-active) row when ``include_inactive=True``."""

    def __init__(self, member: SpaceChannelMember | None):
        self.member = member

    async def find_membership(self, business_id, business_type, user_id, include_inactive=False):
        if self.member is None:
            return None
        if self.member.status != MembershipStatusEnum.ACTIVE and not include_inactive:
            return None
        return self.member

    async def find_members_by_role(self, channel_id, role):
        return []

    async def count_channel_members(self, channel_id):
        return 1


class _FakeEs:
    async def count_articles(self, source_ids=None, filter_rules=None, **kwargs):
        return 0


def _channel():
    return SimpleNamespace(
        id="channel-review",
        name="123",
        description="",
        visibility=ChannelVisibilityEnum.REVIEW,
        filter_rules=[],
        is_released=True,
        latest_article_update_time=None,
        create_time=datetime.now(),
        source_list=[],
    )


def _service(member: SpaceChannelMember | None) -> ChannelService:
    return ChannelService(
        channel_repository=SimpleNamespace(find_channels_by_ids=_async_return([_channel()])),
        space_channel_member_repository=_MembershipRepo(member),
        channel_info_source_repository=SimpleNamespace(),
        article_es_service=_FakeEs(),
    )


def _async_return(value):
    async def _inner(*args, **kwargs):
        return value

    return _inner


def _pending_member() -> SpaceChannelMember:
    return SpaceChannelMember(
        business_id="channel-review",
        business_type=BusinessTypeEnum.CHANNEL,
        user_id=427,
        user_role=UserRoleEnum.MEMBER,
        status=MembershipStatusEnum.PENDING,
        relation=ChannelRelationEnum.VIEWER,
        update_time=datetime.now(),
    )


async def _empty_context(self, login_user):
    return {}


@pytest.fixture(autouse=True)
def _stub_permissions(monkeypatch):
    # Detail also resolves channel permission ids; keep that out of the DB/OpenFGA
    # path so the test isolates subscription-status resolution.
    monkeypatch.setattr(
        FineGrainedPermissionService,
        "get_effective_permission_ids_async",
        staticmethod(_async_return([])),
    )
    # F040: detail builds the shared F037 context (DB-backed) before resolving
    # permission ids; stub it so this test stays off the DB path.
    monkeypatch.setattr(ChannelService, "_build_channel_permission_context", _empty_context)


@pytest.mark.asyncio
async def test_detail_reports_pending_when_only_pending_membership():
    svc = _service(_pending_member())
    login_user = SimpleNamespace(user_id=427, tenant_id=1)

    detail = await svc.get_channel_detail("channel-review", login_user)

    assert detail.subscription_status == SubscriptionStatusEnum.PENDING


@pytest.mark.asyncio
async def test_detail_reports_not_subscribed_without_membership():
    svc = _service(None)
    login_user = SimpleNamespace(user_id=999, tenant_id=1)

    detail = await svc.get_channel_detail("channel-review", login_user)

    assert detail.subscription_status == SubscriptionStatusEnum.NOT_SUBSCRIBED
