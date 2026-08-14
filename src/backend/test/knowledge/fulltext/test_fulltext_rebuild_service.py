import hashlib

import pytest

from bisheng.knowledge.domain.schemas.knowledge_fulltext_schema import KnowledgeFulltextChunk
from bisheng.knowledge.domain.services.knowledge_fulltext_rebuild_service import (
    KnowledgeFulltextChunkCorruptedError,
    KnowledgeFulltextChunkNotReadyError,
    KnowledgeFulltextRebuildService,
)


def chunk(index: int, text: str, *, file_id: int = 7, knowledge_id: int = 9):
    return KnowledgeFulltextChunk(
        es_id=f"chunk-{index}",
        document_id=file_id,
        knowledge_id=knowledge_id,
        chunk_index=index,
        text=text,
    )


def test_rebuild_unwraps_current_and_legacy_formats_and_deduplicates_exact_overlap():
    service = KnowledgeFulltextRebuildService(max_overlap_chars=20)
    chunks = [
        chunk(0, "<file_title>制度</file_title><paragraph_content>第一章\n共同片段</paragraph_content>"),
        chunk(1, "<file_abstract>摘要</file_abstract><paragraph_content>共同片段\n第二章</paragraph_content>"),
        chunk(2, "标题\n----------\n第二章\n第三章"),
    ]

    rebuilt = service.rebuild(chunks, file_id=7, knowledge_id=9)

    assert rebuilt.content == "第一章\n共同片段\n第二章\n第三章"
    assert rebuilt.chunk_count == 3
    assert rebuilt.content_hash == hashlib.sha256(rebuilt.content.encode("utf-8")).hexdigest()


@pytest.mark.parametrize(
    "chunks",
    [
        [],
        [chunk(1, "缺少首段")],
        [chunk(0, "a"), chunk(0, "b")],
        [chunk(0, "a", file_id=99)],
        [chunk(0, "a", knowledge_id=99)],
    ],
)
def test_rebuild_rejects_missing_or_corrupted_chunk_sequences(chunks):
    service = KnowledgeFulltextRebuildService(max_overlap_chars=20)

    error = KnowledgeFulltextChunkNotReadyError if not chunks else KnowledgeFulltextChunkCorruptedError
    with pytest.raises(error):
        service.rebuild(chunks, file_id=7, knowledge_id=9)


def test_rebuild_keeps_similar_but_not_exact_text():
    service = KnowledgeFulltextRebuildService(max_overlap_chars=20)

    rebuilt = service.rebuild(
        [chunk(0, "设备检修规范"), chunk(1, "设备检修规定")],
        file_id=7,
        knowledge_id=9,
    )

    assert rebuilt.content == "设备检修规范\n设备检修规定"
