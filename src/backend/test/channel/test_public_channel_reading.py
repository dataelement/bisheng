"""A public channel's articles are open to anyone who can find it.

Opening a public channel from the square showed "content needs an approval
before you can read it" — an approval a public channel does not even have.
Being public grants nothing in F048: `visible` arrives only with a
subscription or an explicit grant, so a non-subscriber held nothing and both
the drawer and the article endpoint refused.

Public is a business predicate here, not a permission tuple. An older build
wrote `user:* public_reader` tuples; those were removed deliberately and the
authorization model ignores them, so reviving them is not the fix.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.channel.domain.models.channel import ChannelVisibilityEnum
from bisheng.channel.domain.services.channel_service import ChannelService
from bisheng.common.errcode.channel import ChannelAccessDeniedError

_CHANNEL_ID = "2f00b57642094f59ae84d4c32491fc7a"


def _channel(visibility):
    return SimpleNamespace(
        id=_CHANNEL_ID,
        source_list=["src-1"],
        filter_rules=None,
        visibility=visibility,
    )


def _service(visibility, *, search_response=None):
    response = search_response or SimpleNamespace(data=[], total=0, page=1, page_size=20)
    return ChannelService(
        channel_repository=SimpleNamespace(find_channels_by_ids=AsyncMock(return_value=[_channel(visibility)])),
        space_channel_member_repository=SimpleNamespace(),
        channel_info_source_repository=SimpleNamespace(find_by_ids=AsyncMock(return_value=[])),
        article_es_service=SimpleNamespace(search_articles=AsyncMock(return_value=response)),
        article_read_repository=None,
    )


def _login_user(user_id: int = 150036):
    return SimpleNamespace(user_id=user_id, user_name="gzx001", tenant_id=1)


# The predicate


@pytest.mark.parametrize(
    ("visibility", "expected"),
    [
        (ChannelVisibilityEnum.PUBLIC, True),
        (ChannelVisibilityEnum.REVIEW, False),
        (ChannelVisibilityEnum.PRIVATE, False),
    ],
)
def test_only_a_public_channel_reads_without_subscribing(visibility, expected) -> None:
    assert ChannelService._reads_without_subscribing(_channel(visibility)) is expected


# The article list


async def test_a_stranger_can_list_a_public_channels_articles() -> None:
    """The reported case: a public channel opened from the square."""

    service = _service(ChannelVisibilityEnum.PUBLIC)

    with (
        patch(
            "bisheng.channel.domain.services.channel_service.require_business_action",
            AsyncMock(side_effect=ChannelAccessDeniedError()),
        ) as gate,
        patch.object(ChannelService, "apply_article_sensitive_reviews", AsyncMock(return_value=None)),
    ):
        result = await service.search_channel_articles(
            channel_id=_CHANNEL_ID,
            login_user=_login_user(),
        )

    # The permission call is skipped outright, not called and forgiven: a denial
    # would have raised, and it does not.
    gate.assert_not_awaited()
    assert result.total == 0
    service.article_es_service.search_articles.assert_awaited_once()


async def test_a_review_channel_still_goes_through_the_permission_gate() -> None:
    service = _service(ChannelVisibilityEnum.REVIEW)

    with (
        patch(
            "bisheng.channel.domain.services.channel_service.require_business_action",
            AsyncMock(side_effect=ChannelAccessDeniedError()),
        ),
        pytest.raises(ChannelAccessDeniedError),
    ):
        await service.search_channel_articles(channel_id=_CHANNEL_ID, login_user=_login_user())

    service.article_es_service.search_articles.assert_not_awaited()


async def test_a_public_channel_still_refuses_an_anonymous_caller() -> None:
    """Open to anyone signed in is not the same as open to the internet."""

    service = _service(ChannelVisibilityEnum.PUBLIC)

    with pytest.raises(ChannelAccessDeniedError):
        await service.search_channel_articles(channel_id=_CHANNEL_ID, login_user=None)

    service.article_es_service.search_articles.assert_not_awaited()


# The action set the client reads


async def test_the_action_set_reports_visible_for_a_public_channel() -> None:
    """The drawer decides from `actions`, so allowing the read is not enough."""

    service = _service(ChannelVisibilityEnum.PUBLIC)

    with patch(
        "bisheng.channel.domain.services.channel_service.batch_check_business_actions",
        AsyncMock(return_value={_CHANNEL_ID: frozenset()}),
    ):
        actions = await service._get_channel_actions(
            _CHANNEL_ID,
            _login_user(),
            channel=_channel(ChannelVisibilityEnum.PUBLIC),
        )

    assert "visible" in actions


async def test_the_action_set_is_untouched_for_a_review_channel() -> None:
    service = _service(ChannelVisibilityEnum.REVIEW)

    with patch(
        "bisheng.channel.domain.services.channel_service.batch_check_business_actions",
        AsyncMock(return_value={_CHANNEL_ID: frozenset({"edit"})}),
    ):
        actions = await service._get_channel_actions(
            _CHANNEL_ID,
            _login_user(),
            channel=_channel(ChannelVisibilityEnum.REVIEW),
        )

    assert actions == {"edit"}
