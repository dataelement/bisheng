from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from bisheng.knowledge.domain.schemas.knowledge_fulltext_schema import (
    KnowledgeFulltextFileSnapshot,
)
from bisheng.knowledge.domain.services.knowledge_fulltext_document_service import (
    KnowledgeFulltextDocumentService,
    KnowledgeFulltextProjectionAction,
)


def snapshot(**updates):
    values = {
        "file_id": 11,
        "knowledge_id": 22,
        "file_type": "FILE",
        "status": "SUCCESS",
        "deleted_at": None,
        "file_name": "制度.pdf",
        "alias_name": "",
        "summary": "摘要",
        "file_source": "upload",
        "knowledge_name": "制度库",
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 1, 2, tzinfo=timezone.utc),
    }
    values.update(updates)
    return KnowledgeFulltextFileSnapshot(**values)


@pytest.mark.parametrize(
    ("item", "expected"),
    [
        (snapshot(), KnowledgeFulltextProjectionAction.UPSERT),
        (snapshot(status="PROCESSING"), KnowledgeFulltextProjectionAction.KEEP),
        (snapshot(status="FAILED"), KnowledgeFulltextProjectionAction.DELETE),
        (
            snapshot(deleted_at=datetime(2026, 1, 3, tzinfo=timezone.utc)),
            KnowledgeFulltextProjectionAction.DELETE,
        ),
        (
            snapshot(
                logical_document_id=5,
                entry_type="publish",
                entry_status="active",
                projection_status="pending",
                is_primary_version=True,
            ),
            KnowledgeFulltextProjectionAction.RETRY,
        ),
        (
            snapshot(
                logical_document_id=5,
                entry_type="publish",
                entry_status="active",
                projection_status="ready",
                is_primary_version=True,
            ),
            KnowledgeFulltextProjectionAction.UPSERT,
        ),
    ],
)
def test_eligibility_matrix(item, expected):
    assert KnowledgeFulltextDocumentService.decide(item) == expected


def test_document_builder_uses_whitelist_and_title_fallback():
    service = KnowledgeFulltextDocumentService(index_schema_version=1)
    item = snapshot(
        tags=["安全", "制度"],
        original_knowledge_id=33,
        original_knowledge_name="来源制度库",
        user_metadata={"secret": "must-not-leak"},
    )

    document = service.build(
        item,
        content="正文",
        chunk_count=2,
        content_hash="abc",
        sync_revision=4,
        indexed_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
    )
    payload = document.model_dump(mode="json")

    assert payload["display_title"] == "制度.pdf"
    assert payload["tags"] == ["安全", "制度"]
    assert payload["original_knowledge_id"] == 33
    assert payload["original_knowledge_name"] == "来源制度库"
    assert "tenant_id" not in payload
    assert "user_metadata" not in payload
    assert "acl" not in payload


def test_snapshot_rejects_unknown_contract_fields():
    with pytest.raises(ValidationError):
        KnowledgeFulltextFileSnapshot(**snapshot().model_dump(), tenant_id=1)
