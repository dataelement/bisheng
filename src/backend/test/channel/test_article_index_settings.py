"""AC-14, AC-15, AC-16, AC-17: article-only primary-shard configuration."""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from pydantic import ValidationError

from bisheng.channel.domain.es import article_index
from bisheng.core.config.settings import ChannelArticleIndexConf


@pytest.mark.parametrize("invalid", [0, -1, True, False, 1.5, "3", None])
def test_invalid_shards_are_rejected(invalid):
    with pytest.raises(ValidationError):
        ChannelArticleIndexConf(number_of_shards=invalid)


async def test_sync_async_creation_share_policy_and_preserve_base_settings():
    assert ChannelArticleIndexConf().number_of_shards == 3
    with patch.object(article_index, "_configured_shards", return_value=5):
        before = article_index.ARTICLE_SETTINGS.copy()
        async_es = AsyncMock()
        async_es.indices.exists.return_value = False
        await article_index.ensure_article_index_exists(async_es)
        sync_es = Mock()
        sync_es.indices.exists.return_value = False
        article_index.ensure_article_index_exists_sync(sync_es)
        assert async_es.indices.create.call_args.kwargs["body"] == sync_es.indices.create.call_args.kwargs["body"]
        assert sync_es.indices.create.call_args.kwargs["body"]["settings"]["index"]["number_of_shards"] == 5
        assert article_index.ARTICLE_SETTINGS == before
        async_es.indices.exists.return_value = True
        async_es.indices.create.reset_mock()
        await article_index.ensure_article_index_exists(async_es)
        async_es.indices.create.assert_not_called()
