"""分页、局部失败及写入成功但响应丢失后的幂等恢复。"""

import ast
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.knowledge.domain.contracts.shared_storage_reconcile import MetadataRepair, ReconcileQueryError
from bisheng.knowledge.rag.shared_storage_reconcile import SharedStorageReconcileAdapter
from test.knowledge.test_shared_storage_reconcile import rows, snapshot


class Collection:
    def __init__(self, data):
        self.data = deepcopy(data)
        self.next_pk = 10000
        self.lose_insert_response = False
        self.closed = False
        self.schema = SimpleNamespace(fields=[SimpleNamespace(name=k, params={"dim": 2}) for k in data[0]])

    def query_iterator(self, *, expr, **kwargs):
        ids = ast.literal_eval(expr.split(" in ")[1])
        data = deepcopy([r for r in self.data if r["canonical_document_id"] in ids])
        collection = self

        class Iterator:
            def next(self):
                page = data[:2]
                del data[:2]
                return page

            def close(self):
                collection.closed = True

        return Iterator()

    def insert(self, data, **kwargs):
        for row in data:
            self.next_pk += 1
            self.data.append({**deepcopy(row), "pk": self.next_pk})
        if self.lose_insert_response:
            self.lose_insert_response = False
            raise TimeoutError("insert accepted but response lost")
        return SimpleNamespace(insert_count=len(data))

    def delete(self, *, expr, **kwargs):
        ids = ast.literal_eval(expr.split(" in ")[1])
        self.data = [r for r in self.data if r["pk"] not in ids]


class ES:
    def __init__(self, data):
        self.data = deepcopy(data)
        self.hits = []
        self.cleared = False
        self.partial = False
        self.fail_id = None

    def options(self, **kwargs):
        return self

    def search(self, **kwargs):
        assert kwargs["source"] is True
        ids = kwargs["query"]["terms"]["metadata.canonical_document_id"]
        self.hits = [
            {
                "_id": str(row["canonical_document_id"]),
                "_seq_no": 0,
                "_primary_term": 1,
                "_source": {
                    "metadata": {k: v for k, v in row.items() if k not in {"text", "vector", "pk"}},
                    "text": row["text"],
                },
            }
            for row in self.data
            if row["canonical_document_id"] in ids
        ]
        return self.scroll()

    def scroll(self, **kwargs):
        hits, self.hits = self.hits[:2], self.hits[2:]
        return {"_scroll_id": "scroll", "hits": {"hits": hits}, "timed_out": self.partial}

    def clear_scroll(self, **kwargs):
        self.cleared = True

    def bulk(self, *, operations, **kwargs):
        items = []
        for action, body in zip(operations[::2], operations[1::2], strict=True):
            assert "if_seq_no" in action["update"]
            doc_id = int(action["update"]["_id"])
            if doc_id == self.fail_id:
                items.append({"update": {"status": 409, "error": {"type": "conflict"}}})
            else:
                for row in self.data:
                    if row["canonical_document_id"] == doc_id:
                        row.update(body["script"]["params"]["metadata"])
                items.append({"update": {"status": 200}})
        return {"items": items}


def adapter(data):
    route = SimpleNamespace(
        tenant_id=1,
        shared_enabled=True,
        index_name="shared",
        collection_name="shared",
        routing_version=1,
        write_frozen=False,
        embedding_model_id=7,
        schema_fingerprint="fp",
    )
    collection = Collection(data)
    writer = SimpleNamespace(
        collection=collection,
        _assert_writable=lambda **kw: None,
        _check_membership_limits=lambda ids: None,
    )
    return SharedStorageReconcileAdapter(
        route,
        guard=AsyncMock(),
        routing_provider=lambda _: route,
        writer_factory=lambda _: (writer, None),
        es_client=ES(data),
    )


@pytest.mark.parametrize("side", ["es", "milvus"])
async def test_reads_all_pages_and_closes_cursor(side):
    data = [{**rows(snapshot(i))[0], "pk": i} for i in range(1, 8)]
    store = adapter(data)
    observed = await store.read(side, list(range(1, 8)))
    assert sum(len(items) for items in observed.values()) == 7
    assert store.es_client.cleared if side == "es" else store.writer.collection.closed


async def test_partial_es_query_is_not_empty_success():
    store = adapter([{**rows(snapshot(1))[0], "pk": 1}])
    store.es_client.partial = True
    with pytest.raises(ReconcileQueryError):
        await store.read("es", [1])
    assert store.es_client.cleared


async def test_milvus_lost_insert_response_retry_preserves_vector_and_removes_duplicates():
    s = snapshot(1)
    original = {**rows(s, document_name="旧名称", abstract="旧摘要")[0], "pk": 1}
    store = adapter([original])
    old = await store.read("milvus", [1])
    plans = [MetadataRepair(s, old[1])]
    store.writer.collection.lose_insert_response = True
    with pytest.raises(TimeoutError):
        await store.repair("milvus", plans)
    assert len(store.writer.collection.data) == 2
    assert await store.repair("milvus", plans) == {1: None}
    repaired = store.writer.collection.data
    assert len(repaired) == 1
    assert repaired[0]["vector"] == original["vector"]
    assert repaired[0]["abstract"] is None
    assert repaired[0]["document_name"] == "doc-1"
    pk = repaired[0]["pk"]
    await store.repair("milvus", plans)
    assert store.writer.collection.data[0]["pk"] == pk


async def test_es_bulk_reports_per_document_conflict_and_clears_old_metadata():
    docs = [snapshot(1), snapshot(2)]
    data = [{**rows(s, abstract="旧摘要", user_metadata={"old": True})[0], "pk": s.document_id} for s in docs]
    store = adapter(data)
    store.es_client.fail_id = 2
    old = await store.read("es", [1, 2])
    from dataclasses import replace

    plans = [MetadataRepair(replace(s, metadata={**s.metadata, "user_metadata": {}}), old[s.document_id]) for s in docs]
    assert await store.repair("es", plans) == {1: None, 2: "bulk_status_409"}
    assert store.es_client.data[0]["abstract"] is None
    assert store.es_client.data[0]["user_metadata"] == {}
    assert store.es_client.data[1]["abstract"] == "旧摘要"


async def test_es_read_does_not_require_milvus_available():
    store = adapter([{**rows(snapshot(1))[0], "pk": 1}])

    def unavailable(_):
        raise TimeoutError("milvus unavailable")

    store.writer_factory = unavailable
    assert (await store.read("es", [1]))[1]
    with pytest.raises(TimeoutError):
        await store.read("milvus", [1])
