"""每日全量对账的批处理边界和故障隔离。"""

from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import replace

import pytest

from bisheng.knowledge.domain.contracts.shared_storage_reconcile import DocumentSnapshot
from bisheng.knowledge.domain.services.shared_storage_reconcile_service import SharedStorageReconcileService


def snapshot(doc_id):
    return DocumentSnapshot(
        document_id=doc_id,
        version_id=doc_id * 10,
        file_id=doc_id * 100,
        entry_id=doc_id * 100,
        generation=2,
        membership_generation=2,
        knowledge_ids=(7, 8),
        metadata={"document_name": f"doc-{doc_id}", "abstract": None},
        signature=str(doc_id),
    )


def rows(s, **changes):
    return [
        {
            "canonical_document_id": s.document_id,
            "canonical_version_id": s.version_id,
            "content_file_id": s.file_id,
            "content_generation": s.generation,
            "membership_generation": s.membership_generation,
            "embedding_model_id": "7",
            "chunk_index": 0,
            "text": "正文",
            "vector": [0.1, 0.2],
            "knowledge_ids": list(s.knowledge_ids),
            "knowledge_id": 7,
            **s.metadata,
            **changes,
        }
    ]


class Source:
    def __init__(self, documents):
        self.documents = {s.document_id: s for s in documents}
        self.rebuilds = []
        self.changed = set()

    @asynccontextmanager
    async def open(self):
        yield self

    async def upper_bound(self):
        return max(self.documents, default=0)

    async def page_ids(self, after, upper, limit):
        return [i for i in sorted(self.documents) if after < i <= upper][:limit]

    async def snapshots(self, ids, *, lock=False):
        return {
            i: replace(self.documents[i], signature="changed") if lock and i in self.changed else self.documents[i]
            for i in ids
        }

    async def queue_rebuild(self, s):
        self.rebuilds.append(s.document_id)
        return s.entry_id


class Store:
    embedding_model_id = "7"
    vector_dimension = 2

    def __init__(self, documents):
        self.data = {side: {s.document_id: rows(s) for s in documents} for side in ("es", "milvus")}
        self.events = []
        self.fail_queries = set()
        self.fail_writes = set()

    async def read(self, side, ids):
        self.events.append(("read", side, tuple(ids)))
        if side in self.fail_queries:
            raise TimeoutError("unavailable")
        return deepcopy({i: self.data[side].get(i, []) for i in ids})

    async def repair(self, side, plans):
        self.events.append(("repair", side, tuple(p.snapshot.document_id for p in plans)))
        result = {}
        for p in plans:
            doc_id = p.snapshot.document_id
            if doc_id in self.fail_writes:
                result[doc_id] = "rejected"
            else:
                self.data[side][doc_id] = rows(p.snapshot)
                result[doc_id] = None
        return result


async def run(source, store, **kwargs):
    async def guard():
        return None

    async def dispatch(entry_id):
        return None

    return await SharedStorageReconcileService(
        source_factory=source.open,
        store=store,
        guard=guard,
        dispatch=dispatch,
        run_id="test",
        batch_size=2,
        retry_delays=(0, 0),
        **kwargs,
    ).run()


async def test_compare_whole_batch_before_repair_and_continue_after_failed_document():
    docs = [snapshot(i) for i in range(1, 5)]
    source, store = Source(docs), Store(docs)
    for side in store.data:
        for s in docs:
            store.data[side][s.document_id][0]["document_name"] = "旧名称"
    store.fail_writes.add(1)
    result = await run(source, store)
    assert result["scanned"] == 4
    assert result["status"] == "completed_with_errors"
    assert store.events[:2] == [("read", "es", (1, 2)), ("read", "milvus", (1, 2))]
    for side in store.data:
        assert store.data[side][4][0]["document_name"] == "doc-4"


async def test_unavailable_backend_is_not_missing_content_and_other_backend_repairs():
    docs = [snapshot(1)]
    source, store = Source(docs), Store(docs)
    store.fail_queries.add("es")
    store.data["milvus"][1][0]["document_name"] = "旧名称"
    result = await run(source, store)
    assert not source.rebuilds
    assert store.data["milvus"][1][0]["document_name"] == "doc-1"
    assert result["status"] == "completed_with_errors"


async def test_missing_content_queues_rebuild_but_does_not_claim_repaired():
    docs = [snapshot(1)]
    source, store = Source(docs), Store(docs)
    store.data["es"][1] = []
    result = await run(source, store)
    assert source.rebuilds == [1]
    assert result["rebuild_submitted"] == 1
    assert result["repaired"] == 0


async def test_changed_source_is_not_overwritten():
    docs = [snapshot(1)]
    source, store = Source(docs), Store(docs)
    source.changed.add(1)
    store.data["es"][1][0]["abstract"] = "应清空"
    result = await run(source, store)
    assert result["skipped"] == 1
    assert not any(e[0] == "repair" for e in store.events)


async def test_database_scan_failure_is_incomplete():
    source, store = Source([snapshot(1)]), Store([snapshot(1)])

    async def broken(*args):
        raise ConnectionError("database unavailable")

    source.page_ids = broken
    result = await run(source, store)
    assert result["status"] == "incomplete"
    assert not store.events


@pytest.mark.parametrize("side", ["es", "milvus"])
async def test_content_mismatch_is_not_metadata_repair(side):
    docs = [snapshot(1)]
    source, store = Source(docs), Store(docs)
    store.data[side][1][0]["text"] = "错误正文"
    await run(source, store)
    assert source.rebuilds == [1]
    assert not any(e[0] == "repair" for e in store.events)


async def test_failed_snapshot_batch_does_not_block_next_batch():
    docs = [snapshot(i) for i in range(1, 5)]
    source, store = Source(docs), Store(docs)
    original = source.snapshots

    async def broken(ids, *, lock=False):
        if 1 in ids:
            raise ConnectionError("one batch failed")
        return await original(ids, lock=lock)

    source.snapshots = broken
    store.data["es"][4][0]["document_name"] = "旧名称"
    result = await run(source, store)
    assert result["scanned"] == 4
    assert result["status"] == "completed_with_errors"
    assert store.data["es"][4][0]["document_name"] == "doc-4"


async def test_backend_circuit_stops_repeated_requests_but_other_backend_continues():
    docs = [snapshot(i) for i in range(1, 9)]
    source, store = Source(docs), Store(docs)
    store.fail_queries.add("es")
    result = await run(source, store)
    assert result["scanned"] == 8
    assert len([e for e in store.events if e[:2] == ("read", "es")]) == 9
    assert ("read", "milvus", (7, 8)) in store.events


async def test_lost_lease_stops_before_writes():
    from bisheng.knowledge.domain.contracts.shared_storage_reconcile import ReconcileLockLost

    docs = [snapshot(1)]
    source, store = Source(docs), Store(docs)
    store.data["es"][1][0]["document_name"] = "旧名称"

    async def guard():
        if len(store.events) >= 2:
            raise ReconcileLockLost("lost")

    result = await SharedStorageReconcileService(
        source_factory=source.open,
        store=store,
        guard=guard,
        dispatch=None,
        run_id="lost",
        retry_delays=(0, 0),
    ).run()
    assert result["status"] == "incomplete"
    assert not any(e[0] == "repair" for e in store.events)


async def test_malformed_document_does_not_block_healthy_document():
    docs = [snapshot(1), snapshot(2)]
    source, store = Source(docs), Store(docs)
    store.data["es"][1][0]["chunk_index"] = "invalid"
    store.data["es"][2][0]["document_name"] = "旧名称"
    result = await run(source, store)
    assert result["failed"] == 1
    assert store.data["es"][2][0]["document_name"] == "doc-2"


async def test_tenant_mismatch_never_touches_target_collection():
    source, store = Source([snapshot(1)]), Store([snapshot(1)])
    store.tenant_id = 2
    result = await run(source, store)
    assert result["skipped"] == 1
    assert not store.events


async def test_whole_bulk_failure_splits_and_does_not_block_healthy_document():
    docs = [snapshot(1), snapshot(2)]
    source, store = Source(docs), Store(docs)
    for s in docs:
        store.data["es"][s.document_id][0]["document_name"] = "旧名称"
    original = store.repair

    async def broken(side, plans):
        if any(p.snapshot.document_id == 1 for p in plans):
            raise ValueError("bad document")
        return await original(side, plans)

    store.repair = broken
    result = await run(source, store)
    assert result["failed"] == 1
    assert store.data["es"][2][0]["document_name"] == "doc-2"


async def test_failed_rebuild_dispatch_keeps_pending_and_continues_repairs():
    docs = [snapshot(1), snapshot(2)]
    source, store = Source(docs), Store(docs)
    store.data["es"][1] = []
    store.data["es"][2][0]["document_name"] = "旧名称"

    async def guard():
        return None

    async def broken(entry_id):
        raise ConnectionError("broker unavailable")

    result = await SharedStorageReconcileService(
        source_factory=source.open,
        store=store,
        guard=guard,
        dispatch=broken,
        run_id="dispatch-failure",
        retry_delays=(0, 0),
    ).run()
    assert source.rebuilds == [1]
    assert result["rebuild_pending"] == 1
    assert result["rebuild_submitted"] == 0
    assert result["status"] == "completed_with_errors"
    assert store.data["es"][2][0]["document_name"] == "doc-2"


async def test_membership_generation_is_repaired_without_reembedding():
    docs = [snapshot(1)]
    source, store = Source(docs), Store(docs)
    for side in store.data:
        store.data[side][1][0]["membership_generation"] = 999
    result = await run(source, store)
    assert result["status"] == "completed"
    assert not source.rebuilds
    for side in store.data:
        assert store.data[side][1][0]["membership_generation"] == 2


async def test_repeated_write_failures_suspend_only_affected_backend():
    docs = [snapshot(i) for i in range(1, 9)]
    source, store = Source(docs), Store(docs)
    for side in store.data:
        for s in docs:
            store.data[side][s.document_id][0]["document_name"] = "旧名称"
    original = store.repair

    async def read_only_es(side, plans):
        if side == "es":
            return {p.snapshot.document_id: "bulk_status_403" for p in plans}
        return await original(side, plans)

    store.repair = read_only_es
    result = await run(source, store)
    assert result["scanned"] == 8
    assert ("read", "es", (7, 8)) not in store.events
    assert store.data["milvus"][8][0]["document_name"] == "doc-8"
