"""Chunk reads stay inside files the caller can see."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao
from bisheng.knowledge.domain.services import knowledge_service as knowledge_service_module
from bisheng.knowledge.domain.services.knowledge_file_visibility_service import KnowledgeFileVisibilityService
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService


def _hit(file_id, text):
    return {"_source": {"text": text, "metadata": {"document_id": file_id, "chunk_index": 0}}}


def _install(monkeypatch, *, visible, documents=None, knowledge_type=KnowledgeTypeEnum.SPACE.value):
    opened = []
    searched = []
    decisions = []

    def allow_space(*_args, **_kwargs):
        return SimpleNamespace(id=10, type=knowledge_type)

    async def decide(_self, space_id, file_ids):
        assert space_id == 10
        decisions.append({int(item) for item in file_ids})
        return {int(one) for one in visible if int(one) in {int(item) for item in file_ids}}

    def open_index(*_args, **_kwargs):
        opened.append(True)

        def search(*, index, body):
            searched.append(body)
            terms = body.get("post_filter", {}).get("terms", {}).get("metadata.document_id")
            allowed = {81, 82} if terms is None else {int(one) for one in terms}
            hits = [_hit(file_id, f"body-{file_id}") for file_id in (81, 82) if file_id in allowed]
            return {"hits": {"total": {"value": len(hits)}, "hits": hits}}

        return SimpleNamespace(client=SimpleNamespace(search=search)), "chunks"

    class _ChunkText:
        @staticmethod
        def split_chunk_metadata(text):
            return text

    monkeypatch.setattr(knowledge_service_module, "KnowledgeUtils", _ChunkText)
    monkeypatch.setattr(KnowledgeService, "judge_knowledge_access", staticmethod(allow_space))
    monkeypatch.setattr(KnowledgeFileVisibilityService, "post_filter_visible_files", decide)
    monkeypatch.setattr(
        KnowledgeFileDao, "list_document_ids", staticmethod(lambda _knowledge_id: list(documents or []))
    )
    monkeypatch.setattr(KnowledgeFileDao, "get_file_by_ids", staticmethod(lambda ids: []))
    monkeypatch.setattr(KnowledgeRag, "open_stored_chunk_index_sync", staticmethod(open_index))
    return SimpleNamespace(opened=opened, searched=searched, decisions=decisions)


def test_named_hidden_file_is_rejected_before_the_index_or_violation_text(monkeypatch):
    state = _install(monkeypatch, visible=set(), documents=[81, 82])
    displayed = []
    monkeypatch.setattr(
        KnowledgeService,
        "_violation_display_chunks",
        classmethod(lambda cls, *args, **kwargs: displayed.append(args) or ([], 0)),
    )
    with pytest.raises(HTTPException) as failure:
        KnowledgeService.get_knowledge_chunks(None, SimpleNamespace(user_id=7), 10, [82], None, 1, 10)
    assert failure.value.status_code == 403
    assert state.opened == [] and displayed == []


def test_unscoped_chunk_read_queries_and_returns_only_visible_files(monkeypatch):
    state = _install(monkeypatch, visible={81}, documents=[81, 82])
    rows, total = KnowledgeService.get_knowledge_chunks(None, SimpleNamespace(user_id=7), 10, None, None, 1, 10)
    assert state.searched[0]["post_filter"]["terms"]["metadata.document_id"] == [81]
    assert total == 1 and [row.text for row in rows] == ["body-81"]


def test_legacy_document_library_keeps_its_container_level_chunk_access(monkeypatch):
    """A pre-unification library may have no per-file permission records at all."""

    state = _install(
        monkeypatch,
        visible=set(),
        documents=[81],
        knowledge_type=KnowledgeTypeEnum.NORMAL.value,
    )
    rows, total = KnowledgeService.get_knowledge_chunks(None, SimpleNamespace(user_id=7), 10, [81], None, 1, 10)

    # The container check already admitted this caller; the empty per-file set
    # must not turn a readable legacy library into an empty detail view. The
    # named file still selects its segments, without a permission decision.
    assert state.decisions == []
    assert state.searched[0]["post_filter"]["terms"]["metadata.document_id"] == [81]
    assert total == 1 and [row.text for row in rows] == ["body-81"]


def test_legacy_document_library_unscoped_read_still_uses_the_container_scope(monkeypatch):
    state = _install(
        monkeypatch,
        visible=set(),
        documents=[81, 82],
        knowledge_type=KnowledgeTypeEnum.NORMAL.value,
    )
    _rows, total = KnowledgeService.get_knowledge_chunks(None, SimpleNamespace(user_id=7), 10, None, None, 1, 10)

    assert state.decisions == []
    assert "post_filter" not in state.searched[0]
    assert total == 2
