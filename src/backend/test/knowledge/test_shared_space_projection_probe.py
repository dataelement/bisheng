"""投影内容恢复的多维度决策与真实批量查询边界。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.knowledge.domain.contracts.shared_space_storage import ContentProjectionIdentity
from bisheng.knowledge.domain.contracts.shared_storage_reconcile import ReconcileQueryError
from bisheng.knowledge.rag import shared_space_projection_probe as subject

IDENTITY = ContentProjectionIdentity(7, 91, 501, 100, 4, "1")


def row(index=0, **kwargs):
    return {
        "canonical_document_id": 91,
        "canonical_version_id": 501,
        "content_file_id": 100,
        "content_generation": 4,
        "embedding_model_id": "1",
        "chunk_index": index,
        "text": f"正文{index}",
        "vector": [0.1, 0.2],
        **kwargs,
    }


@pytest.mark.parametrize(
    ("milvus", "es", "action"),
    [
        ([row()], [row()], "reuse"),
        ([row(), row()], [], "reuse"),
        ([], [row(vector=None)], "embed"),
        ([row(vector=[float("nan"), 0.2])], [row()], "embed"),
        ([row(vector=[0.1])], [row()], "embed"),
        ([row(embedding_model_id="old")], [row()], "embed"),
        ([row()], [row(), row(1)], "embed"),
        ([row(), row(1)], [row()], "reuse"),
        ([row()], [row(text="冲突正文")], "defer"),
        ([row(), row(text="重复但正文冲突")], [], "defer"),
        ([row(content_generation=5)], [], "defer"),
        ([row(canonical_version_id=500)], [row(canonical_version_id=500)], "rebuild"),
        ([row(content_file_id=999)], [row(content_file_id=999)], "rebuild"),
        ([row(content_generation=3)], [], "rebuild"),
        ([row(0), row(2)], [row(0), row(2)], "rebuild"),
        ([], [], "rebuild"),
    ],
)
def test_content_recovery_uses_identity_text_chunk_set_and_vector(milvus, es, action):
    result = subject.inspect_content(IDENTITY, milvus, es, 2)
    assert result.action == action
    if action == "reuse":
        assert all(chunk.vector == [0.1, 0.2] for chunk in result.chunks)
    if action == "embed":
        assert any(chunk.vector is None for chunk in result.chunks)


def test_partial_vector_recovery_preserves_existing_vectors_and_metadata():
    result = subject.inspect_content(
        IDENTITY,
        [row(page=8, bbox="kept")],
        [row(), row(1, page=9)],
        2,
    )
    assert result.action == "embed"
    assert result.chunks[0].vector == [0.1, 0.2]
    assert result.chunks[0].metadata["bbox"] == "kept"
    assert result.chunks[1].vector is None and result.chunks[1].metadata["page"] == 9


def make_writer(responses):
    iterator = SimpleNamespace(next=MagicMock(side_effect=[[row()], []]), close=MagicMock())
    writer = SimpleNamespace(
        tenant_id=7,
        schema_spec=SimpleNamespace(embedding_model_id=1),
        collection=SimpleNamespace(
            schema=SimpleNamespace(fields=[SimpleNamespace(name="vector", params={"dim": 2})]),
            query_iterator=MagicMock(return_value=iterator),
        ),
        _assert_writable=MagicMock(),
        _es_index=lambda snapshot: "shared",
        _run_es=AsyncMock(side_effect=responses),
    )
    return writer, iterator


def es_page(rows, total=1, **kwargs):
    return {
        "_scroll_id": "cursor",
        "hits": {
            "total": {"value": total, "relation": "eq"},
            "hits": [{"_source": {"text": item["text"], "metadata": item}} for item in rows],
        },
        **kwargs,
    }


async def test_probe_reads_both_stores_to_exhaustion_in_batches():
    writer, iterator = make_writer([es_page([row()]), es_page([]), {}])
    other = ContentProjectionIdentity(7, 92, 502, 101, 4, "1")
    result = await subject.inspect_projection_content(writer, [IDENTITY, other], guard=AsyncMock())
    assert result[91].action == "reuse" and result[92].action == "rebuild"
    assert iterator.next.call_count == 2
    iterator.close.assert_called_once()
    writer.collection.query_iterator.assert_called_once()
    assert "91, 92" in writer.collection.query_iterator.call_args.kwargs["expr"]
    assert [call.args[0] for call in writer._run_es.await_args_list] == ["search", "scroll", "clear_scroll"]


@pytest.mark.parametrize(
    "page",
    [
        es_page([], timed_out=True),
        es_page([], _shards={"failed": 1}),
        es_page([], total=1),
        {**es_page([row()]), "_scroll_id": None},
    ],
)
async def test_partial_es_results_never_become_a_rebuild_decision(page):
    writer, _ = make_writer([page, {}])
    with pytest.raises(ReconcileQueryError):
        await subject.inspect_projection_content(writer, [IDENTITY], guard=AsyncMock())


async def test_milvus_query_failure_never_becomes_empty_content():
    writer, iterator = make_writer([])
    iterator.next.side_effect = TimeoutError("milvus unavailable")
    with pytest.raises(TimeoutError):
        await subject.inspect_projection_content(writer, [IDENTITY], guard=AsyncMock())
    writer._run_es.assert_not_awaited()
    iterator.close.assert_called_once()


async def test_embedding_recovery_only_embeds_missing_chunks_without_running_pipeline(monkeypatch):
    from bisheng.knowledge.domain.contracts.shared_space_storage import SharedContentChunk
    from bisheng.knowledge.domain.services import shared_space_content_loader as loader

    monkeypatch.setattr(loader, "KnowledgeFilePipeline", MagicMock(side_effect=AssertionError("must not parse")))
    monkeypatch.setattr(loader, "resolve_space_shared_routing", lambda *_: SimpleNamespace(embedding_model_id=1))
    embeddings = SimpleNamespace(embed_documents=MagicMock(return_value=[[0.3, 0.4]]))
    monkeypatch.setattr(loader.LLMService, "get_bisheng_knowledge_embedding_sync", lambda **_: embeddings)
    chunks = (
        SharedContentChunk(0, "保留", [0.1, 0.2], metadata={"page": 1}),
        SharedContentChunk(1, "补向量", metadata={"page": 2}),
    )
    result = await loader.embed_shared_content_chunks(SimpleNamespace(tenant_id=7, user_id=1), chunks)
    embeddings.embed_documents.assert_called_once_with(["补向量"])
    assert result[0] is chunks[0]
    assert result[1].vector == [0.3, 0.4] and result[1].metadata == {"page": 2}
