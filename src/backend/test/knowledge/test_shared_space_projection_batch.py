"""真实批量适配器的部分写入失败、批次与旧数据保护。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.knowledge.domain.contracts.shared_space_storage import MembershipUpdateRequest, SharedProjectionWrite
from bisheng.knowledge.rag import shared_space_projection_batch as subject
from bisheng.knowledge.rag.shared_space_storage import SHARED_MILVUS_PK_FIELD


def make_row(document_id, index=0):
    return {
        SHARED_MILVUS_PK_FIELD: document_id * 1000 + index,
        "canonical_document_id": document_id,
        "canonical_version_id": document_id + 100,
        "content_generation": 4,
        "membership_generation": 1,
        "chunk_index": index,
        "knowledge_ids": [1],
        "tenant_id": 7,
        "text": "keep",
        "vector": [0.1, 0.2],
    }


def make_plan(document_id, ids=(1, 2)):
    return SharedProjectionWrite(MembershipUpdateRequest(7, document_id, ids, 2, 4))


def make_writer(failed_document=None):
    async def es(method, **kwargs):
        if method == "bulk":
            items = []
            for index in range(0, len(kwargs["operations"]), 2):
                doc_id = int(kwargs["operations"][index]["index"]["_id"].split("-")[0])
                items.append({"index": {"status": 503 if doc_id == failed_document else 201}})
            return {"items": items, "errors": failed_document is not None}
        return {"failures": [], "timed_out": False}

    return SimpleNamespace(
        tenant_id=7,
        schema_spec=SimpleNamespace(embedding_model_id=1),
        _assert_writable=MagicMock(),
        _check_membership_limits=MagicMock(),
        _es_index=lambda snapshot: "shared",
        _conf=lambda: SimpleNamespace(es_routing_enabled=True),
        _es_doc_id=lambda identity, index: f"{identity.canonical_document_id}-{index}",
        _es_doc_source=lambda row: row.copy(),
        _es_doc_query=lambda **kwargs: {"bool": {"filter": [{"term": {"doc": kwargs["canonical_document_id"]}}]}},
        _run_es=AsyncMock(side_effect=es),
        _run_milvus=AsyncMock(),
    )


async def test_membership_bulk_preserves_payload_and_keeps_failed_document_old_rows(monkeypatch):
    rows = [make_row(1), make_row(2)]
    load = AsyncMock(return_value=rows)
    monkeypatch.setattr(subject, "_load_rows", load)
    writer = make_writer(failed_document=2)
    errors = await subject.apply_projection_batch(writer, [make_plan(1), make_plan(2)], guard=AsyncMock())
    assert set(errors) == {2}
    load.assert_awaited_once_with(writer, [1, 2])
    insert, delete = writer._run_milvus.await_args_list
    assert insert.args[0] == "insert" and len(insert.args[1]) == 2
    assert all(
        row["vector"] == [0.1, 0.2] and row["text"] == "keep" and row["knowledge_ids"] == [1, 2]
        for row in insert.args[1]
    )
    assert "1000" in delete.kwargs["expr"] and "2000" not in delete.kwargs["expr"]
    assert rows[0]["knowledge_ids"] == [1]


async def test_chunk_count_does_not_limit_input_and_bulk_requests_are_bounded(monkeypatch):
    rows = [make_row(1, index) for index in range(1201)]
    monkeypatch.setattr(subject, "_load_rows", AsyncMock(return_value=rows))
    writer = make_writer()
    assert await subject.apply_projection_batch(writer, [make_plan(1)], guard=AsyncMock()) == {}
    inserts = [call for call in writer._run_milvus.await_args_list if call.args[0] == "insert"]
    assert [len(call.args[1]) for call in inserts] == [500, 500, 201]
    assert len([call for call in writer._run_es.await_args_list if call.args[0] == "bulk"]) == 3


async def test_stale_generation_and_cross_tenant_are_rejected_before_write(monkeypatch):
    newer = make_row(1)
    newer["membership_generation"] = 9
    monkeypatch.setattr(subject, "_load_rows", AsyncMock(return_value=[newer]))
    writer = make_writer()
    errors = await subject.apply_projection_batch(writer, [make_plan(1)], guard=AsyncMock())
    assert "stale" in errors[1]
    writer._run_milvus.assert_not_awaited()
    with pytest.raises(ValueError, match="tenant"):
        await subject.apply_projection_batch(
            writer,
            [SharedProjectionWrite(MembershipUpdateRequest(8, 2, (1,), 2, 4))],
            guard=AsyncMock(),
        )


async def test_content_upsert_and_tombstone_share_batch_without_deleting_before_insert(monkeypatch):
    from types import MethodType

    from bisheng.knowledge.domain.contracts.shared_space_storage import (
        ContentProjectionIdentity,
        ContentUpsertRequest,
        SharedContentChunk,
    )
    from bisheng.knowledge.rag.shared_space_storage import MilvusEsSharedSpaceStorageWriter

    monkeypatch.setattr(subject, "_load_rows", AsyncMock(return_value=[make_row(1), make_row(2)]))
    writer = make_writer()
    writer._build_chunk_row = MethodType(MilvusEsSharedSpaceStorageWriter._build_chunk_row, writer)
    writer._check_embedding_model = MagicMock()
    content = ContentUpsertRequest(
        ContentProjectionIdentity(7, 1, 101, 100, 5, "1"), (1, 2),
        [SharedContentChunk(chunk_index=0, text="new content", vector=[0.3, 0.4])],
    )
    plans = [SharedProjectionWrite(MembershipUpdateRequest(7, 1, (1, 2), 5, 5), content), make_plan(2, ())]
    assert await subject.apply_projection_batch(writer, plans, guard=AsyncMock()) == {}
    inserts, deletes = writer._run_milvus.await_args_list
    assert inserts.args[0] == "insert" and deletes.args[0] == "delete"
    assert len(inserts.args[1]) == 1 and inserts.args[1][0]["content_generation"] == 5
    assert inserts.args[1][0]["text"] == "new content"
    assert "1000" in deletes.kwargs["expr"] and "2000" in deletes.kwargs["expr"]
    assert [call.args[0] for call in writer._run_es.await_args_list] == ["bulk", "delete_by_query"]
