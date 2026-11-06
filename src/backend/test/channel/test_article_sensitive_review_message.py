"""Article reading uses review wording while preserving the safety decision."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.channel.domain.services.channel_service import ChannelService
from bisheng.common.errcode.channel import ArticleSensitiveViolationError
from bisheng.sensitive_word.domain.services.sensitive_word_policy_service import DEFAULT_AUTO_REPLY


@pytest.mark.parametrize("can_view_sensitive", [False, True])
def test_article_review_replaces_upload_default_without_changing_access(can_view_sensitive):
    review = ChannelService._to_sensitive_review(
        enabled=True,
        hits=[SimpleNamespace(word="拦截词", count=1)],
        auto_reply=DEFAULT_AUTO_REPLY,
        can_view_sensitive=can_view_sensitive,
    )
    assert review.auto_reply == "该文章未通过安全审查，无法查看详情"  # noqa: RUF001
    assert review.violated is True
    assert review.can_view is can_view_sensitive
    assert [(hit.word, hit.count) for hit in review.hits] == [("拦截词", 1)]


def test_article_review_preserves_custom_message():
    review = ChannelService._to_sensitive_review(
        enabled=True,
        hits=[SimpleNamespace(word="拦截词", count=1)],
        auto_reply="请联系安全管理员",
        can_view_sensitive=False,
    )
    assert review.auto_reply == "请联系安全管理员"
    assert review.can_view is False


async def test_direct_article_read_still_denied_with_review_wording(monkeypatch):
    review = ChannelService._to_sensitive_review(
        enabled=True,
        hits=[SimpleNamespace(word="拦截词", count=1)],
        auto_reply=DEFAULT_AUTO_REPLY,
        can_view_sensitive=False,
    )
    article = SimpleNamespace(sensitive_review=review)
    monkeypatch.setattr(ChannelService, "apply_article_sensitive_reviews", AsyncMock())
    with pytest.raises(ArticleSensitiveViolationError) as exc:
        await ChannelService.ensure_article_sensitive_view_allowed(article, SimpleNamespace())
    assert exc.value.message == "该文章未通过安全审查，无法查看详情"  # noqa: RUF001
