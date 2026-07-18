"""Regression: channel article detail must let admins / ReBAC-granted users read
without subscribing — mirroring knowledge-space APPROVAL access.

``get_article_detail`` previously gated content purely on an ACTIVE membership
(``current_membership.status == ACTIVE``), so a super/tenant admin or a user
granted ``view_channel`` via ReBAC was denied a REVIEW channel's article unless
they applied and got approved. Knowledge-space APPROVAL content, by contrast,
resolves through ReBAC where admins short-circuit to owner-equivalent
permissions and read directly.

The fix keeps the ACTIVE-member fast path but, for non-members, falls back to
``_get_channel_permission_ids`` and allows the read when ``view_channel`` is
present. ``find_membership`` is ACTIVE-only for channels, so a PENDING applicant
resolves to ``None`` and gains no membership-derived permission — the approval
gate stays intact. These tests lock that behaviour.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from bisheng.channel.domain.models.channel import ChannelVisibilityEnum
from bisheng.channel.domain.services.channel_service import ChannelService
from bisheng.common.errcode.channel import ChannelAccessDeniedError
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

_SENTINEL = object()


def _async_return(value):
    async def _inner(*args, **kwargs):
        return value

    return _inner


class _MembershipRepo:
    """Mirrors the real ACTIVE-only default: a non-active row is only returned
    when ``include_inactive=True``."""

    def __init__(self, member: SpaceChannelMember | None):
        self.member = member

    async def find_membership(self, business_id, business_type, user_id, include_inactive=False):
        if self.member is None:
            return None
        if self.member.status != MembershipStatusEnum.ACTIVE and not include_inactive:
            return None
        return self.member


class _FakeEs:
    """Returns a truthy article that matches the channel filter so the flow
    proceeds past the permission gate to the response builder."""

    async def get_article(self, article_id):
        return SimpleNamespace(source_id="")  # falsy source_id → skip source enrichment

    async def count_articles(self, source_ids=None, filter_rules=None, include_article_ids=None, **kwargs):
        return 1  # article belongs to this channel


def _channel():
    return SimpleNamespace(
        id="channel-review",
        name="review-channel",
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
        article_read_repository=None,  # skip read-record bookkeeping
    )


def _active_member() -> SpaceChannelMember:
    return SpaceChannelMember(
        business_id="channel-review",
        business_type=BusinessTypeEnum.CHANNEL,
        user_id=100,
        user_role=UserRoleEnum.MEMBER,
        status=MembershipStatusEnum.ACTIVE,
        relation=ChannelRelationEnum.VIEWER,
        update_time=datetime.now(),
    )


def _pending_member() -> SpaceChannelMember:
    return SpaceChannelMember(
        business_id="channel-review",
        business_type=BusinessTypeEnum.CHANNEL,
        user_id=200,
        user_role=UserRoleEnum.MEMBER,
        status=MembershipStatusEnum.PENDING,
        relation=ChannelRelationEnum.VIEWER,
        update_time=datetime.now(),
    )


@pytest.fixture(autouse=True)
def _isolate_side_effects(monkeypatch):
    # Keep sensitive-word review and the response-schema mapping out of the test;
    # the behaviour under test is the permission gate only.
    monkeypatch.setattr(
        ChannelService,
        "ensure_article_sensitive_view_allowed",
        staticmethod(_async_return(None)),
    )
    monkeypatch.setattr(
        ChannelService,
        "_to_article_detail_response",
        staticmethod(lambda article: _SENTINEL),
    )


def _stub_rebac(monkeypatch, permission_ids):
    monkeypatch.setattr(
        FineGrainedPermissionService,
        "get_effective_permission_ids_async",
        staticmethod(_async_return(list(permission_ids))),
    )


async def test_admin_or_rebac_grant_can_view_without_membership(monkeypatch):
    # Admin / ReBAC-granted user resolves to view_channel even with no membership.
    _stub_rebac(monkeypatch, {"view_channel"})
    svc = _service(None)
    login_user = SimpleNamespace(user_id=1, tenant_id=1)

    result = await svc.get_article_detail("article-1", "channel-review", login_user)

    assert result is _SENTINEL


async def test_pending_applicant_is_denied(monkeypatch):
    # PENDING membership is hidden by find_membership (ACTIVE-only) and yields no
    # view_channel — the approval gate must not be bypassed.
    _stub_rebac(monkeypatch, set())
    svc = _service(_pending_member())
    login_user = SimpleNamespace(user_id=200, tenant_id=1)

    with pytest.raises(ChannelAccessDeniedError):
        await svc.get_article_detail("article-1", "channel-review", login_user)


async def test_unrelated_user_without_permission_is_denied(monkeypatch):
    _stub_rebac(monkeypatch, set())
    svc = _service(None)
    login_user = SimpleNamespace(user_id=999, tenant_id=1)

    with pytest.raises(ChannelAccessDeniedError):
        await svc.get_article_detail("article-1", "channel-review", login_user)


async def test_active_member_still_allowed(monkeypatch):
    # Regression: the ACTIVE-member fast path is unchanged and must not even need
    # the ReBAC lookup. Make ReBAC blow up to prove it isn't consulted.
    async def _boom(*args, **kwargs):
        raise AssertionError("ReBAC should not be consulted for an ACTIVE member")

    monkeypatch.setattr(
        FineGrainedPermissionService,
        "get_effective_permission_ids_async",
        staticmethod(_boom),
    )
    svc = _service(_active_member())
    login_user = SimpleNamespace(user_id=100, tenant_id=1)

    result = await svc.get_article_detail("article-1", "channel-review", login_user)

    assert result is _SENTINEL
