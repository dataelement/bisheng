"""F034 — migrate_file_vectors worker tests (pure mocks, no real Milvus/ES).

Covers: read source ES → re-insert into target (re-embed) → delete source →
REBUILDING→SUCCESS; failure → FAILED; idempotent no-op when source is empty.
"""

from unittest.mock import MagicMock, patch

from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileStatus

_W = "bisheng.worker.knowledge.move_worker"


def _file(file_id=100, kid=2, status=KnowledgeFileStatus.REBUILDING.value):
    return MagicMock(id=file_id, knowledge_id=kid, user_id=1, status=status)


def _space(sid, index=None, col=None):
    return MagicMock(id=sid, index_name=index or f"idx_{sid}", collection_name=col or f"col_{sid}")


def _run(*, file, source, target, chunks, target_milvus=None, target_es=None, source_es=None, source_milvus=None):
    """Invoke migrate_file_vectors with all I/O boundaries patched; return the
    status-update calls made on KnowledgeFileDao."""
    from bisheng.worker.knowledge.move_worker import migrate_file_vectors

    status_calls = []
    src_es = source_es or MagicMock()
    tgt_milvus = target_milvus or MagicMock()
    tgt_es = target_es or MagicMock()
    src_milvus = source_milvus or MagicMock()

    def _init_es(space):
        return src_es if space.id == source.id else tgt_es

    def _init_milvus(_uid, knowledge=None, **k):
        return src_milvus if knowledge.id == source.id else tgt_milvus

    with (
        patch(f"{_W}.KnowledgeFileDao.query_by_id_sync", return_value=file),
        patch(
            f"{_W}.KnowledgeDao.query_by_id", side_effect=lambda sid: {source.id: source, target.id: target}.get(sid)
        ),
        patch(
            f"{_W}.KnowledgeFileDao.update_file_status",
            side_effect=lambda ids, status, reason=None: status_calls.append((tuple(ids), status, reason)),
        ),
        patch(f"{_W}.get_all_es_chunks", return_value=chunks),
        patch(f"{_W}.KnowledgeRag.init_knowledge_es_vectorstore_sync", side_effect=_init_es),
        patch(f"{_W}.KnowledgeRag.init_knowledge_milvus_vectorstore_sync", side_effect=_init_milvus),
    ):
        migrate_file_vectors.run(file.id, source.id)

    return status_calls, tgt_milvus, tgt_es, src_es, src_milvus


def test_migrate_reembeds_into_target_and_deletes_source():
    file = _file(100, kid=2)
    source, target = _space(1), _space(2)
    chunks = [
        {"_source": {"text": "hello", "metadata": {"document_id": 100, "knowledge_id": 1, "pk": 7}}},
        {"_source": {"text": "world", "metadata": {"document_id": 100, "knowledge_id": 1, "pk": 8}}},
    ]
    status, tgt_milvus, tgt_es, src_es, src_milvus = _run(file=file, source=source, target=target, chunks=chunks)

    # re-inserted 2 chunks into target, with knowledge_id rewritten to target + pk dropped
    tgt_milvus.add_texts.assert_called_once()
    _, kw = tgt_milvus.add_texts.call_args
    assert kw["texts"] == ["hello", "world"]
    assert all(m["knowledge_id"] == 2 for m in kw["metadatas"])
    assert all("pk" not in m for m in kw["metadatas"])
    tgt_es.add_texts.assert_called_once()
    # source deleted (ES by query, Milvus by document_id)
    src_es.client.delete_by_query.assert_called_once()
    src_milvus.col.delete.assert_called_once()
    # status settled to SUCCESS
    assert status[-1] == ((100,), KnowledgeFileStatus.SUCCESS, None)


def test_migrate_empty_source_is_noop_but_settles_status():
    file = _file(101, kid=2)
    source, target = _space(1), _space(2)
    status, tgt_milvus, _, src_es, _ = _run(file=file, source=source, target=target, chunks=[])

    tgt_milvus.add_texts.assert_not_called()
    src_es.client.delete_by_query.assert_not_called()
    assert status[-1] == ((101,), KnowledgeFileStatus.SUCCESS, None)


def test_migrate_failure_marks_file_failed():
    file = _file(102, kid=2)
    source, target = _space(1), _space(2)
    boom = MagicMock()
    boom.add_texts.side_effect = RuntimeError("milvus down")
    chunks = [{"_source": {"text": "x", "metadata": {"document_id": 102}}}]
    status, *_ = _run(file=file, source=source, target=target, chunks=chunks, target_milvus=boom)

    assert status[-1][0] == (102,)
    assert status[-1][1] == KnowledgeFileStatus.FAILED


def test_migrate_same_space_finalizes_without_moving():
    # source == target (e.g. a duplicate dispatch after settle) → just finalize.
    file = _file(103, kid=1)
    same = _space(1)
    status, tgt_milvus, _, src_es, _ = _run(file=file, source=same, target=same, chunks=[])
    tgt_milvus.add_texts.assert_not_called()
    src_es.client.delete_by_query.assert_not_called()
    assert status[-1] == ((103,), KnowledgeFileStatus.SUCCESS, None)
