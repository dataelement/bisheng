from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.channel.domain.schemas.article_schema import ArticleDocument
from bisheng.channel.domain.services.article_es_service import ArticleEsService


def _article(title: str) -> ArticleDocument:
    return ArticleDocument(source_type=1, source_id="source", title=title)


async def test_mget_existing_ids_returns_only_found_documents():
    service = ArticleEsService()
    service._es_client = SimpleNamespace(
        mget=AsyncMock(
            return_value={
                "docs": [
                    {"_id": "A", "found": True},
                    {"_id": "B", "found": False},
                ]
            }
        )
    )
    service.ensure_index = AsyncMock()

    assert await service.mget_existing_ids(["A", "B"]) == {"A"}


async def test_detailed_bulk_maps_success_and_failure_ids():
    service = ArticleEsService()
    service._es_client = SimpleNamespace()
    service.ensure_index = AsyncMock()
    errors = [{"index": {"_id": "B", "status": 429, "error": {"type": "busy"}}}]

    with patch(
        "bisheng.channel.domain.services.article_es_service.es_helpers.async_bulk",
        new=AsyncMock(return_value=(1, errors)),
    ):
        result = await service.bulk_index_articles_detailed({"A": _article("A"), "B": _article("B")})

    assert result.success_ids == {"A"}
    assert set(result.failed_ids) == {"B"}


async def test_strict_refresh_propagates_failure():
    service = ArticleEsService()
    service._es_client = SimpleNamespace(indices=SimpleNamespace(refresh=AsyncMock(side_effect=RuntimeError("down"))))
    service.ensure_index = AsyncMock()

    with pytest.raises(RuntimeError, match="down"):
        await service.refresh_index()
