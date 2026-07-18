"""F040 T2: channel detail must (a) reuse a single shared permission context
(F037 ``_build_channel_permission_context``) instead of re-deriving it inline, and
(b) look up the user's membership at most once per request (the ACTIVE-only +
include_inactive fallback collapse into one ``include_inactive=True`` lookup).

Equivalence guard: ``test_channel_detail_subscription_status.py`` already locks the
PENDING/NOT_SUBSCRIBED subscription-status semantics — these tests must not change
that, only the call count and the context passing.
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


def _async_return(value):
    async def _inner(*args, **kwargs):
        return value

    return _inner


class _CountingMembershipRepo:
    """Holds the user's membership rows; counts membership lookups. ``rows`` is the
    full set for this user/channel (multi-grant model) — the split derives
    highest-active vs highest-any from it, mirroring the real repository."""

    def __init__(self, member: SpaceChannelMember | None = None, rows: list[SpaceChannelMember] | None = None):
        if rows is None:
            rows = [member] if member is not None else []
        self.rows = rows
        self.find_membership_calls = 0

    @staticmethod
    def _highest(rows):
        # Mirror the real _highest_membership: max by relation rank (owner > manager
        # > editor > viewer). VIEWER is lowest, so a higher-ranked row wins.
        order = {
            ChannelRelationEnum.OWNER: 3,
            ChannelRelationEnum.MANAGER: 2,
            ChannelRelationEnum.EDITOR: 1,
            ChannelRelationEnum.VIEWER: 0,
        }
        return max(rows, key=lambda r: order.get(r.relation, 0)) if rows else None

    async def find_membership(self, business_id, business_type, user_id, include_inactive=False):
        self.find_membership_calls += 1
        candidates = (
            self.rows if include_inactive else [r for r in self.rows if r.status == MembershipStatusEnum.ACTIVE]
        )
        return self._highest(candidates)

    async def find_membership_split(self, business_id, business_type, user_id):
        self.find_membership_calls += 1
        highest_active = self._highest([r for r in self.rows if r.status == MembershipStatusEnum.ACTIVE])
        highest_any = self._highest(self.rows)
        return highest_active, highest_any

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


def _service(repo) -> ChannelService:
    return ChannelService(
        channel_repository=SimpleNamespace(find_channels_by_ids=_async_return([_channel()])),
        space_channel_member_repository=repo,
        channel_info_source_repository=SimpleNamespace(),
        article_es_service=_FakeEs(),
    )


def _member(
    status: MembershipStatusEnum,
    relation: ChannelRelationEnum = ChannelRelationEnum.VIEWER,
) -> SpaceChannelMember:
    return SpaceChannelMember(
        business_id="channel-review",
        business_type=BusinessTypeEnum.CHANNEL,
        user_id=427,
        user_role=UserRoleEnum.MEMBER,
        status=status,
        relation=relation,
        update_time=datetime.now(),
    )


async def _empty_context(self, login_user):
    return {}


@pytest.fixture(autouse=True)
def _stub_permissions(monkeypatch):
    monkeypatch.setattr(
        FineGrainedPermissionService,
        "get_effective_permission_ids_async",
        staticmethod(_async_return([])),
    )
    # F040: detail now builds the shared context (DB-backed); stub it out so these
    # tests isolate membership-count / context-passing from the DB/OpenFGA path.
    monkeypatch.setattr(ChannelService, "_build_channel_permission_context", _empty_context)


@pytest.mark.asyncio
async def test_detail_dedups_membership_lookup_for_pending():
    """AC-06: a single membership lookup, even when only a PENDING row exists."""
    repo = _CountingMembershipRepo(_member(MembershipStatusEnum.PENDING))
    detail = await _service(repo).get_channel_detail("channel-review", SimpleNamespace(user_id=427, tenant_id=1))
    assert detail.subscription_status == SubscriptionStatusEnum.PENDING  # equivalence preserved
    assert repo.find_membership_calls == 1


@pytest.mark.asyncio
async def test_detail_dedups_membership_lookup_for_active():
    """AC-06: a single membership lookup for an ACTIVE member."""
    repo = _CountingMembershipRepo(_member(MembershipStatusEnum.ACTIVE))
    await _service(repo).get_channel_detail("channel-review", SimpleNamespace(user_id=427, tenant_id=1))
    assert repo.find_membership_calls == 1


@pytest.mark.asyncio
async def test_higher_ranked_inactive_row_does_not_mask_active_membership(monkeypatch):
    """Review regression: in the multi-grant model a user can hold both an ACTIVE
    VIEWER row and a higher-ranked PENDING MANAGER row. Collapsing to a single
    highest-rank lookup would pick the PENDING row and drop ACTIVE gating
    (fail-closed). The split lookup must still gate on the ACTIVE row while showing
    the PENDING subscription status — all from one membership query (AC-06)."""
    captured = {}

    async def _capture_permission_ids(self, channel_id, login_user, current_membership, *, context=None):
        captured["current_membership"] = current_membership
        return []

    monkeypatch.setattr(ChannelService, "_get_channel_permission_ids", _capture_permission_ids)

    active_viewer = _member(MembershipStatusEnum.ACTIVE, ChannelRelationEnum.VIEWER)
    pending_manager = _member(MembershipStatusEnum.PENDING, ChannelRelationEnum.MANAGER)
    repo = _CountingMembershipRepo(rows=[active_viewer, pending_manager])

    detail = await _service(repo).get_channel_detail("channel-review", SimpleNamespace(user_id=427, tenant_id=1))

    # Gating uses the ACTIVE row (not masked by the higher-ranked PENDING one)...
    assert captured["current_membership"] is active_viewer
    # ...while the displayed subscription status reflects the PENDING application.
    assert detail.subscription_status == SubscriptionStatusEnum.PENDING
    # Still a single membership lookup.
    assert repo.find_membership_calls == 1


@pytest.mark.asyncio
async def test_detail_passes_shared_context_to_permission_ids(monkeypatch):
    """AC-04: detail builds the F037 shared context once and passes it down,
    instead of letting ``_get_channel_permission_ids`` re-derive it inline."""
    repo = _CountingMembershipRepo(_member(MembershipStatusEnum.ACTIVE))
    svc = _service(repo)

    sentinel = {"_f040_sentinel": True}

    async def _fake_ctx(self, login_user):
        return sentinel

    captured = {}

    async def _spy_perm_ids(self, channel_id, login_user, membership=None, *, context=None):
        captured["context"] = context
        return set()

    monkeypatch.setattr(ChannelService, "_build_channel_permission_context", _fake_ctx)
    monkeypatch.setattr(ChannelService, "_get_channel_permission_ids", _spy_perm_ids)

    await svc.get_channel_detail("channel-review", SimpleNamespace(user_id=427, tenant_id=1))

    assert captured["context"] is sentinel
