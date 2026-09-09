"""The article list is gated by the F048 ``visible`` decision and nothing else.

F048 replaced the old "ACTIVE membership or a ``view_channel`` permission id"
block with ``require_business_action(action="visible")`` in both the article
list and the article detail. A later merge resurrected the old block in the
list alone, still calling ``_get_channel_permission_ids`` — a helper F048 had
deleted. Every reader who holds the channel through a Grant rather than a
subscription row (a department grant, say) then got a 500 with
``'ChannelService' object has no attribute '_get_channel_permission_ids'``.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.channel.domain.services.channel_service import ChannelService
from bisheng.common.errcode.channel import ChannelAccessDeniedError

_CHANNEL_ID = "ba05d6abbb214bbf92de036115a748fa"


def _service(*, search_response) -> ChannelService:
    channel = SimpleNamespace(id=_CHANNEL_ID, source_list=["src-1"], filter_rules=None)
    return ChannelService(
        channel_repository=SimpleNamespace(find_channels_by_ids=AsyncMock(return_value=[channel])),
        # Left un-stubbed on purpose: the list must not consult membership at all.
        space_channel_member_repository=SimpleNamespace(),
        channel_info_source_repository=SimpleNamespace(find_by_ids=AsyncMock(return_value=[])),
        article_es_service=SimpleNamespace(search_articles=AsyncMock(return_value=search_response)),
        article_read_repository=None,
    )


def _login_user(user_id: int = 150036):
    return SimpleNamespace(user_id=user_id, user_name="gzx001", tenant_id=1)


async def test_grant_holder_without_a_subscription_row_can_list_articles():
    """The reported 500: access via a department Grant, no membership row."""

    response = SimpleNamespace(data=[], total=0, page=1, page_size=20)
    service = _service(search_response=response)

    with (
        patch(
            "bisheng.channel.domain.services.channel_service.require_business_action",
            AsyncMock(return_value=None),
        ) as gate,
        patch.object(ChannelService, "apply_article_sensitive_reviews", AsyncMock(return_value=None)),
    ):
        result = await service.search_channel_articles(
            channel_id=_CHANNEL_ID,
            login_user=_login_user(),
        )

    assert result is response
    gate.assert_awaited_once()
    assert gate.await_args.kwargs["action"] == "visible"
    assert gate.await_args.kwargs["resource_id"] == _CHANNEL_ID


async def test_a_denied_visible_decision_stops_the_list_before_elasticsearch():
    response = SimpleNamespace(data=[], total=0, page=1, page_size=20)
    service = _service(search_response=response)

    with (
        patch(
            "bisheng.channel.domain.services.channel_service.require_business_action",
            AsyncMock(side_effect=ChannelAccessDeniedError()),
        ),
        pytest.raises(ChannelAccessDeniedError),
    ):
        await service.search_channel_articles(
            channel_id=_CHANNEL_ID,
            login_user=_login_user(),
        )

    service.article_es_service.search_articles.assert_not_awaited()


async def test_an_anonymous_caller_is_refused_before_the_permission_call():
    response = SimpleNamespace(data=[], total=0, page=1, page_size=20)
    service = _service(search_response=response)

    with (
        patch(
            "bisheng.channel.domain.services.channel_service.require_business_action",
            AsyncMock(return_value=None),
        ) as gate,
        pytest.raises(ChannelAccessDeniedError),
    ):
        await service.search_channel_articles(channel_id=_CHANNEL_ID, login_user=None)

    gate.assert_not_awaited()
