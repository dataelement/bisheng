"""真实 writer 的元数据迁移契约，存储用有状态替身，不启动解析器。"""

from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace as N

import pytest

from bisheng.knowledge.domain.contracts.shared_space_storage import ContentProjectionIdentity, ContentRelocationRequest
from bisheng.knowledge.rag import shared_space_metadata_migration as migration
from bisheng.knowledge.rag.shared_space_storage import MilvusEsSharedSpaceStorageWriter


@pytest.mark.parametrize("merge", [False, True])
async def test_metadata_migration_preserves_payload_retries_partial_write_and_batches(monkeypatch, merge):
    writer = object.__new__(MilvusEsSharedSpaceStorageWriter)
    writer.tenant_id = 1
    writer.schema_spec = N(embedding_model_id=7)
    writer._assert_writable = lambda **_: N(index_name="shared")
    writer._check_membership_limits = lambda _: None
    writer._conf = lambda: N(es_routing_enabled=True)
    writer._es_index = lambda _: "shared"
    source = ContentProjectionIdentity(1, 91, 501, 100, 3, "7")
    target = replace(source, canonical_document_id=92, content_generation=5) if merge else source
    rows = [
        {
            "pk": index + 1,
            "text": f"unchanged-{index}",
            "vector": [0.25, 0.5],
            "chunk_index": index,
            "canonical_document_id": 91,
            "canonical_version_id": 501,
            "content_file_id": 100,
            "content_generation": 3,
            "membership_generation": 3,
            "embedding_model_id": "7",
            "knowledge_ids": [10, 30],
        }
        for index in range(5)
    ]
    es = {}
    next_pk = 100
    bulk_sizes = []
    fail = True

    async def read(_writer, identity):
        return deepcopy(
            [
                row
                for row in rows
                if row["canonical_document_id"] == identity.canonical_document_id
                and row["content_generation"] == identity.content_generation
            ]
        )

    async def milvus(method, *args, **kwargs):
        nonlocal next_pk
        if method == "insert":
            for row in args[0]:
                next_pk += 1
                rows.append({**deepcopy(row), "pk": next_pk})
        elif "pk in" in kwargs["expr"]:
            import ast

            ids = ast.literal_eval(kwargs["expr"].split(" in ")[1])
            rows[:] = [row for row in rows if row["pk"] not in ids]

    async def elastic(method, **kwargs):
        nonlocal fail
        if method == "bulk":
            operations = kwargs["operations"]
            bulk_sizes.append(len(operations) // 2)
            for index in range(0, len(operations), 2):
                es[operations[index]["index"]["_id"]] = operations[index + 1]
            if fail:
                fail = False
                return {"errors": True}
            return {"errors": False}
        if method == "count":
            return {"count": len(es), "_shards": {"failed": 0}}
        return {"failures": []}

    monkeypatch.setattr(migration, "_rows", read)
    monkeypatch.setattr(migration, "WRITE_BATCH_SIZE", 2)
    writer._run_milvus, writer._run_es = milvus, elastic
    request = ContentRelocationRequest(source, target, (20, 30), 6)
    with pytest.raises(RuntimeError, match="incomplete"):
        await writer.relocate_content(request)
    assert len([row for row in rows if row["canonical_document_id"] == 91]) >= 5
    await writer.relocate_content(request)
    await writer.relocate_content(request)
    migrated = await read(writer, target)
    assert len(migrated) == 5
    assert {row["text"] for row in migrated} == {f"unchanged-{index}" for index in range(5)}
    assert all(row["vector"] == [0.25, 0.5] and row["knowledge_ids"] == [20, 30] for row in migrated)
    assert max(bulk_sizes) <= 2
    if merge:
        assert len(await read(writer, source)) == 5


async def test_missing_shared_content_fails_without_reparse(monkeypatch):
    writer = object.__new__(MilvusEsSharedSpaceStorageWriter)
    writer.tenant_id = 1
    writer._assert_writable = lambda **_: N()
    writer._check_membership_limits = lambda _: None

    async def empty(*_):
        return []

    monkeypatch.setattr(migration, "_rows", empty)
    identity = ContentProjectionIdentity(1, 91, 501, 100, 3, "7")
    with pytest.raises(RuntimeError, match="source chunks are missing"):
        await writer.relocate_content(ContentRelocationRequest(identity, identity, (20,), 4))


async def test_content_reader_consumes_all_pages_and_closes_iterator():
    pages = iter([[{"chunk_index": 0}], [{"chunk_index": 1}], []])
    closed = []
    iterator = N(next=lambda: next(pages), close=lambda: closed.append(True))
    writer = N(_doc_expr=lambda **_: "scope", collection=N(query_iterator=lambda **_: iterator))
    identity = ContentProjectionIdentity(1, 91, 501, 100, 3, "7")
    assert await migration._rows(writer, identity) == [{"chunk_index": 0}, {"chunk_index": 1}]
    assert closed == [True]


async def test_overwritten_content_delete_rejects_es_partial_failure():
    from unittest.mock import AsyncMock
    from bisheng.knowledge.domain.contracts.shared_space_storage import ContentDeleteRequest

    writer = object.__new__(MilvusEsSharedSpaceStorageWriter)
    writer.tenant_id = 1
    writer.schema_spec = N(embedding_model_id=7)
    writer._assert_writable = lambda **_: N()
    writer._es_index = lambda _: "shared"
    writer._run_milvus = AsyncMock()
    writer._run_es = AsyncMock(return_value={"failures": [{"reason": "unavailable"}]})
    with pytest.raises(RuntimeError, match="deletion was incomplete"):
        await writer.delete_content(ContentDeleteRequest(1, 92))
