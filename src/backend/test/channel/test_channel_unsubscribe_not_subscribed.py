"""Unsubscribing from a channel you never subscribed to is an answerable state.

The followed list is resolved from the F048 `visible` decision, so it also holds
channels a viewer reached through a Grant rather than a subscription. Those
carry no membership row, and asking to unsubscribe from one raised a bare
`ValueError` — surfacing as HTTP 500 with an English sentence the client could
not branch on.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.channel.domain.services.channel_service import ChannelService
from bisheng.common.errcode.channel import (
    ChannelGrantedNotSubscribedError,
    ChannelNotSubscribedError,
)
from bisheng.common.models.space_channel_member import MembershipStatusEnum

_CHANNEL_ID = "ba05d6abbb214bbf92de036115a748fa"


def _service(*, membership) -> ChannelService:
    return ChannelService(
        channel_repository=SimpleNamespace(),
        space_channel_member_repository=SimpleNamespace(
            find_membership=AsyncMock(return_value=membership),
            find_channel_membership_sources=AsyncMock(return_value=[]),
        ),
        channel_info_source_repository=SimpleNamespace(),
    )


def _login_user(user_id: int = 150041):
    return SimpleNamespace(user_id=user_id, user_name="gzx006", tenant_id=1)


async def test_no_membership_at_all_says_the_channel_was_granted():
    """Reached through a Grant, so there is no subscription of theirs to end."""
    service = _service(membership=None)

    with pytest.raises(ChannelGrantedNotSubscribedError) as exc_info:
        await service.unsubscribe_channel(_CHANNEL_ID, _login_user())

    assert exc_info.value.code == 19015


@pytest.mark.parametrize(
    "status",
    [MembershipStatusEnum.PENDING, MembershipStatusEnum.REJECTED],
    ids=["still-pending", "rejected"],
)
async def test_an_application_that_never_became_a_subscription_says_so(status):
    service = _service(membership=SimpleNamespace(id=1, status=status))

    with pytest.raises(ChannelNotSubscribedError) as exc_info:
        await service.unsubscribe_channel(_CHANNEL_ID, _login_user())

    assert exc_info.value.code == 19014


async def test_neither_case_is_a_bare_value_error():
    """A ValueError here reaches the client as a 500 with no code to branch on."""
    for membership in (None, SimpleNamespace(id=1, status=MembershipStatusEnum.PENDING)):
        service = _service(membership=membership)
        with pytest.raises(Exception) as exc_info:
            await service.unsubscribe_channel(_CHANNEL_ID, _login_user())
        assert type(exc_info.value) is not ValueError
