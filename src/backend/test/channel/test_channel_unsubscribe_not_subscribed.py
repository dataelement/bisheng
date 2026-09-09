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
from bisheng.common.errcode.channel import ChannelNotSubscribedError
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


@pytest.mark.parametrize(
    "membership",
    [
        None,
        SimpleNamespace(id=1, status=MembershipStatusEnum.PENDING),
        SimpleNamespace(id=1, status=MembershipStatusEnum.REJECTED),
    ],
    ids=["granted-but-never-subscribed", "still-pending", "rejected"],
)
async def test_unsubscribe_without_an_active_membership_is_a_business_error(membership):
    service = _service(membership=membership)

    with pytest.raises(ChannelNotSubscribedError) as exc_info:
        await service.unsubscribe_channel(_CHANNEL_ID, _login_user())

    assert exc_info.value.code == 19014


async def test_the_error_is_not_a_bare_value_error():
    """A ValueError here reaches the client as a 500 with no code to branch on."""
    service = _service(membership=None)

    with pytest.raises(Exception) as exc_info:
        await service.unsubscribe_channel(_CHANNEL_ID, _login_user())

    assert type(exc_info.value) is not ValueError
    assert isinstance(exc_info.value, ChannelNotSubscribedError)
