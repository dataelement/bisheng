from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.knowledge.domain.contracts.fulltext_reconcile import Observation, ReconcileLeaseLost
from bisheng.knowledge.domain.schemas.knowledge_fulltext_schema import (
    KnowledgeFulltextChunk,
    KnowledgeFulltextChunkSource,
    KnowledgeFulltextFileSnapshot,
)
from bisheng.knowledge.domain.services.knowledge_fulltext_reconcile_service import KnowledgeFulltextReconcileService


def snapshot(file_id=1, **updates):
    return KnowledgeFulltextFileSnapshot(
        file_id=file_id,
        knowledge_id=9,
        file_type="FILE",
        status=updates.pop("status", "2"),
        file_name="制度.pdf",
        file_source="upload",
        knowledge_name="制度库",
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 2),
        **updates,
    )


class Harness:
    def __init__(self, snapshots):
        self.snapshots = snapshots
        self.documents = {}
        self.writes = []
        self.reject = {}
        self.chunk_errors = {}
        self.repo = SimpleNamespace(
            source=SimpleNamespace(
                snapshots=AsyncMock(side_effect=self.load), chunk_sources=AsyncMock(side_effect=self.sources)
            ),
            claim_mutations=AsyncMock(side_effect=self.claim),
            finish_mutations=AsyncMock(),
            state=SimpleNamespace(has_issue=AsyncMock(return_value=True)),
            request_repair=AsyncMock(return_value="repair_pending"),
        )
        self.es = SimpleNamespace(
            read=AsyncMock(side_effect=self.read),
            chunks=AsyncMock(side_effect=self.chunks),
            write=AsyncMock(side_effect=self.write),
            totals=AsyncMock(side_effect=lambda ids: {i: {"preview_count": 8, "download_count": 3} for i in ids}),
        )
        self.service = KnowledgeFulltextReconcileService(
            repository_factory=self.factory,
            es=self.es,
            guard=AsyncMock(),
            now=lambda: datetime(2026, 9, 17),
            body_batch_size=20,
        )

    @asynccontextmanager
    async def factory(self):
        yield self.repo

    async def load(self, ids):
        return {i: self.snapshots[i] for i in ids if i in self.snapshots}

    async def sources(self, snapshots):
        return {
            s.file_id: KnowledgeFulltextChunkSource(index_name="rag", file_id=s.file_id, knowledge_id=9)
            for s in snapshots
        }

    async def read(self, ids):
        return {i: Observation(self.documents.get(i), 1, 1) for i in ids}

    async def chunks(self, sources):
        return {
            s.file_id: self.chunk_errors.get(
                s.file_id,
                [
                    KnowledgeFulltextChunk(
                        es_id=str(s.file_id), document_id=s.file_id, knowledge_id=9, chunk_index=0, text="正文"
                    )
                ],
            )
            for s in sources
        }

    async def claim(self, changes, snapshots, owner, now):
        return {c.file_id: (c.file_id, 1) for c in changes if c.file_id not in self.reject}, self.reject

    async def write(self, changes):
        self.writes.append(changes)
        for change in changes:
            if change.document is None:
                self.documents.pop(change.file_id, None)
            else:
                self.documents[change.file_id] = change.document
        return {c.file_id: None for c in changes}


async def test_batch_repairs_and_deletes_while_bad_file_and_processing_file_are_isolated():
    h = Harness({1: ValueError("bad metadata"), 2: snapshot(2), 4: snapshot(4, status="1")})
    h.documents = {3: {"file_id": 3}, 4: {"file_id": 4, "content": "旧正文"}}
    failures, good = await h.service.batch([1, 2, 3, 4], "run")
    assert set(failures) == {1, 4}
    assert good == {2: "repaired", 3: "deleted"}
    assert h.documents[4]["content"] == "旧正文"
    assert [m.file_id for m in h.writes[0]] == [2, 3]
    assert h.es.read.await_count == 2
    assert h.es.write.await_count == 1


async def test_consistent_second_scan_does_not_rewrite_and_actual_text_drift_is_detected():
    h = Harness({1: snapshot()})
    await h.service.batch([1], "run")
    _, good = await h.service.batch([1], "run")
    assert good == {1: "consistent"}
    assert h.es.write.await_count == 1
    h.documents[1] = {**h.documents[1], "content": "损坏正文"}
    _, good = await h.service.batch([1], "run")
    assert good == {1: "repaired"}
    assert h.documents[1]["content"] == "正文"


async def test_restore_or_busy_outbox_between_scan_and_write_prevents_deletion():
    h = Harness({})
    h.documents = {1: {"file_id": 1}}
    h.reject = {1: "source_changed"}
    bad, good = await h.service.batch([1], "run")
    assert bad == {1: "source_changed"}
    assert not good
    assert h.documents[1] == {"file_id": 1}
    h.es.write.assert_not_awaited()


async def test_unknown_bulk_result_is_verified_before_retry():
    h = Harness({1: snapshot(), 2: snapshot(2)})

    async def uncertain(changes):
        h.documents[1] = changes[0].document
        return {1: TimeoutError(), 2: TimeoutError()}

    h.es.write.side_effect = uncertain
    bad, good = await h.service.batch([1, 2], "run")
    assert good == {1: "repaired"}
    assert set(bad) == {2}
    assert h.es.write.await_count == 1


async def test_chunk_damage_creates_repair_intent_and_other_file_continues():
    h = Harness({1: snapshot(), 2: snapshot(2)})
    h.chunk_errors[1] = []
    bad, good = await h.service.batch([1, 2], "run")
    assert bad == {1: "repair_pending"}
    assert good == {2: "repaired"}
    h.repo.request_repair.assert_awaited_once()


async def test_lost_lease_never_becomes_an_ordinary_file_failure():
    h = Harness({1: snapshot()})
    h.service.guard.side_effect = ReconcileLeaseLost()
    with pytest.raises(ReconcileLeaseLost):
        await h.service.batch([1], "run")
    h.es.write.assert_not_awaited()


async def test_failed_batch_isolated_from_next_batch():
    h = Harness({i: snapshot(i) for i in range(1, 5)})
    h.service.body_batch_size = 2

    async def load(ids):
        if 1 in ids:
            raise ConnectionError("first batch failed")
        return await h.load(ids)

    h.repo.source.snapshots.side_effect = load
    bad, good = await h.service.batch([1, 2, 3, 4], "run")
    assert set(bad) == {1, 2}
    assert set(good) == {3, 4}


async def test_repair_intent_failure_and_malformed_es_field_do_not_block_other_files():
    h = Harness({1: snapshot(), 2: snapshot(2)})
    h.chunk_errors[1] = []
    h.repo.request_repair.side_effect = ConnectionError("intent storage")
    h.documents[2] = {"file_id": 2, "created_at": "invalid date"}
    bad, good = await h.service.batch([1, 2], "run")
    assert set(bad) == {1}
    assert good == {2: "repaired"}


async def test_repeated_whole_batch_failures_pause_without_silent_success():
    from bisheng.knowledge.domain.contracts.fulltext_reconcile import ReconcileDependencyUnavailable

    h = Harness({})
    h.service.body_batch_size = 2
    h.repo.source.snapshots.side_effect = ConnectionError("database unavailable")
    with pytest.raises(ReconcileDependencyUnavailable):
        await h.service.batch(list(range(1, 9)), "run")
    assert h.repo.source.snapshots.await_count == 3


async def test_bulk_timeout_after_write_is_verified_and_new_record_restores_engagement():
    h = Harness({1: snapshot()})

    async def uncertain(changes):
        h.documents[1] = changes[0].document
        raise TimeoutError("response lost")

    h.es.write.side_effect = uncertain
    bad, good = await h.service.batch([1], "run")
    assert not bad
    assert good == {1: "repaired"}
    assert h.documents[1]["preview_count"] == 8
    assert h.documents[1]["download_count"] == 3


async def test_reverse_pass_only_reads_fulltext_for_cleanup_candidates():
    h = Harness({1: snapshot(), 2: snapshot(2)})
    h.documents[3] = {"file_id": 3}
    bad, good = await h.service.reverse_batch([1, 2, 3], "run")
    assert not bad
    assert good == {1: "reverse_existing", 2: "reverse_existing", 3: "deleted"}
    assert all(call.args[0] == [3] for call in h.es.read.call_args_list)
    assert all(call.args[0] == [] for call in h.es.chunks.call_args_list)
