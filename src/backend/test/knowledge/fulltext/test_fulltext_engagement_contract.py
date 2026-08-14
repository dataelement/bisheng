from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_index_repository_impl import (
    KnowledgeFulltextIndexRepositoryImpl,
)
from bisheng.knowledge.domain.schemas.knowledge_fulltext_schema import (
    KnowledgeFulltextDocument,
    KnowledgeFulltextEngagementCounts,
)


def test_engagement_fields_are_strict_non_negative_and_default_to_zero():
    counts = KnowledgeFulltextEngagementCounts(file_id=11)

    assert counts.preview_count == 0
    assert counts.download_count == 0
    with pytest.raises(ValidationError):
        KnowledgeFulltextEngagementCounts(file_id=11, preview_count=-1)

    document = KnowledgeFulltextDocument.minimal(
        file_id=11,
        knowledge_id=22,
        file_name="制度.pdf",
        content="正文",
        sync_revision=1,
    )
    payload = document.model_dump(mode="json")
    assert payload["preview_count"] == 0
    assert payload["download_count"] == 0
    assert payload["engagement_updated_at"] is None


def test_engagement_mapping_is_additive_without_analyzer_changes():
    repository = KnowledgeFulltextIndexRepositoryImpl(AsyncMock())

    properties = repository.build_index_definition()["mappings"]["properties"]

    assert properties["preview_count"] == {"type": "long"}
    assert properties["download_count"] == {"type": "long"}
    assert properties["engagement_updated_at"] == {"type": "date"}


async def test_complete_upsert_preserves_existing_counts_and_seeds_new_document():
    client = AsyncMock()
    repository = KnowledgeFulltextIndexRepositoryImpl(client)
    document = KnowledgeFulltextDocument.minimal(
        file_id=11,
        knowledge_id=22,
        file_name="制度.pdf",
        content="新正文",
        sync_revision=2,
    ).model_copy(
        update={
            "preview_count": 7,
            "download_count": 3,
            "engagement_updated_at": datetime(2026, 8, 13, tzinfo=timezone.utc),
        }
    )

    await repository.upsert(document)

    kwargs = client.update.await_args.kwargs
    assert kwargs["id"] == "11"
    assert "preview_count" not in kwargs["doc"]
    assert "download_count" not in kwargs["doc"]
    assert "engagement_updated_at" not in kwargs["doc"]
    assert kwargs["upsert"]["preview_count"] == 7
    assert kwargs["upsert"]["download_count"] == 3


async def test_absolute_bulk_update_has_no_upsert_and_is_item_isolated():
    client = AsyncMock()
    client.bulk.return_value = {
        "items": [
            {"update": {"_id": "11", "status": 200, "result": "updated"}},
            {"update": {"_id": "12", "status": 200, "result": "noop"}},
            {"update": {"_id": "13", "status": 404, "error": {"type": "document_missing_exception"}}},
            {"update": {"_id": "14", "status": 429, "error": {"type": "es_rejected_execution_exception"}}},
        ]
    }
    repository = KnowledgeFulltextIndexRepositoryImpl(client)
    counts = [
        KnowledgeFulltextEngagementCounts(file_id=file_id, preview_count=file_id, download_count=1)
        for file_id in (11, 12, 13, 14)
    ]

    result = await repository.bulk_update_engagement(
        counts,
        updated_at=datetime(2026, 8, 13, tzinfo=timezone.utc),
    )

    operations = client.bulk.await_args.kwargs["operations"]
    assert all("upsert" not in operation for operation in operations)
    assert "content" not in str(operations)
    assert result.updated_ids == [11]
    assert result.noop_ids == [12]
    assert result.missing_ids == [13]
    assert result.failed_ids == [14]
