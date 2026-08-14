from datetime import datetime

import pytest

from bisheng.knowledge.domain.schemas.knowledge_fulltext_schema import (
    KnowledgeFulltextAutoRepairSource,
)
from bisheng.knowledge.domain.services.knowledge_fulltext_auto_repair_service import (
    KnowledgeFulltextAutoRepairDecision,
    KnowledgeFulltextAutoRepairService,
)
from bisheng.knowledge.domain.services.knowledge_fulltext_rebuild_service import (
    KnowledgeFulltextChunkCorruptedError,
    KnowledgeFulltextChunkNotReadyError,
    KnowledgeFulltextProjectionNotReadyError,
)


@pytest.mark.parametrize(
    ("exception", "retry_count", "expected"),
    [
        (
            KnowledgeFulltextChunkCorruptedError("duplicate chunk indexes"),
            0,
            KnowledgeFulltextAutoRepairDecision.REQUEST,
        ),
        (
            KnowledgeFulltextChunkNotReadyError("no chunks"),
            0,
            KnowledgeFulltextAutoRepairDecision.RETRY_ONLY,
        ),
        (
            KnowledgeFulltextChunkNotReadyError("no chunks"),
            1,
            KnowledgeFulltextAutoRepairDecision.REQUEST,
        ),
        (ConnectionError("rag es unavailable"), 7, KnowledgeFulltextAutoRepairDecision.IGNORE),
        (
            KnowledgeFulltextProjectionNotReadyError("projection pending"),
            7,
            KnowledgeFulltextAutoRepairDecision.IGNORE,
        ),
    ],
)
def test_auto_repair_decision_only_accepts_confirmed_chunk_source_errors(exception, retry_count, expected):
    assert KnowledgeFulltextAutoRepairService.decide(exception, retry_count=retry_count) is expected


def test_auto_repair_fingerprint_changes_only_with_source_version_inputs():
    source = KnowledgeFulltextAutoRepairSource(
        file_id=7,
        knowledge_id=9,
        md5="content-md5",
        object_name="knowledge/7.pdf",
        split_rule='{"chunk_size": 500}',
        desired_content_generation=3,
    )

    first = KnowledgeFulltextAutoRepairService.fingerprint(source)
    assert first == KnowledgeFulltextAutoRepairService.fingerprint(source.model_copy())
    assert first != KnowledgeFulltextAutoRepairService.fingerprint(
        source.model_copy(update={"split_rule": '{"chunk_size": 800}'})
    )
    assert first != KnowledgeFulltextAutoRepairService.fingerprint(
        source.model_copy(update={"desired_content_generation": 4})
    )
    assert len(first) == 64


def test_auto_repair_payload_contains_no_source_or_content_values():
    source = KnowledgeFulltextAutoRepairSource(
        file_id=7,
        knowledge_id=9,
        md5="secret-md5",
        object_name="secret-object-name.pdf",
        split_rule="secret-split-rule",
        desired_content_generation=0,
    )

    payload = KnowledgeFulltextAutoRepairService.new_payload(
        fingerprint=KnowledgeFulltextAutoRepairService.fingerprint(source),
        error_type="KnowledgeFulltextChunkCorruptedError",
        now=datetime(2026, 8, 13, 18, 0, 0),
    )
    serialized = str(payload)

    assert payload["state"] == "requested"
    assert payload["attempt_count"] == 1
    assert "secret-md5" not in serialized
    assert "secret-object-name" not in serialized
    assert "secret-split-rule" not in serialized
