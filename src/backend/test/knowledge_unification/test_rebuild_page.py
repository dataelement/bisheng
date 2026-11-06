"""T065: real chunk pagination and retained retry source without middleware.

The chunk processor is exercised directly with transport-only stores. The
legacy/J1-facing entries also use the existing real Source/Model/R2 fixture.
"""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.worker import tenant_context as workers
from bisheng.worker.knowledge import rebuild_knowledge_worker as module
from test.knowledge_unification import test_kn_worker_model_source as fixtures

store = fixtures.store
tenant = fixtures.tenant
business = fixtures.business
admission = fixtures.admission
rebuild = fixtures.rebuild


class ChunkSource:
    def __init__(self, count=10003, fail_scroll=False):
        self.hits = [
            {
                "_id": str(i),
                "_source": {
                    "text": f"manual chunk {i}",
                    "metadata": {
                        "document_id": 701,
                        "knowledge_id": 40,
                        "pk": i,
                        "manual": True,
                        "custom": {"tag": "kept"},
                    },
                },
            }
            for i in range(count)
        ]
        self.position = 0
        self.page_size = None
        self.fail_scroll = fail_scroll
        self.clear_scroll = Mock()
        self.delete_by_query = Mock(side_effect=AssertionError("retry text must survive"))

    def search(self, *, index, body, size=None, scroll=None):
        assert index == "idx40" and body["query"]["match"]["metadata.document_id"] == 701
        self.page_size = size or body.get("size", 10)
        self.position = self.page_size
        return {"_scroll_id": "cursor" if scroll else None, "hits": {"hits": deepcopy(self.hits[: self.position])}}

    def scroll(self, **kwargs):
        if self.fail_scroll:
            raise RuntimeError("page unavailable")
        start = self.position
        self.position += self.page_size
        return {"_scroll_id": "cursor", "hits": {"hits": deepcopy(self.hits[start : self.position])}}


def test_more_than_ten_thousand_manual_chunks_and_metadata_are_preserved():
    source = ChunkSource()
    original = deepcopy(source.hits)
    vector = SimpleNamespace(add_texts=Mock())
    file = SimpleNamespace(id=701, knowledge_id=40)
    assert module._process_single_file(file, SimpleNamespace(client=source), "idx40", vector)
    inserted = vector.add_texts.call_args.kwargs
    assert inserted["texts"] == [row["_source"]["text"] for row in original]
    assert inserted["metadatas"] == [
        {key: value for key, value in row["_source"]["metadata"].items() if key != "pk"} for row in original
    ]
    assert source.hits == original and source.page_size < 10000
    source.clear_scroll.assert_called_once_with(scroll_id="cursor")
    source.delete_by_query.assert_not_called()


def test_page_failure_closes_scroll_and_keeps_all_source_text():
    source = ChunkSource(fail_scroll=True)
    original = deepcopy(source.hits)
    vector = SimpleNamespace(add_texts=Mock())
    with pytest.raises(RuntimeError, match="page unavailable"):
        module._process_single_file(SimpleNamespace(id=701), SimpleNamespace(client=source), "idx40", vector)
    assert source.hits == original
    source.clear_scroll.assert_called_once_with(scroll_id="cursor")
    vector.add_texts.assert_not_called()


def test_vector_failure_does_not_remove_manual_source_chunks():
    source = ChunkSource(count=3)
    before = deepcopy(source.hits)
    vector = SimpleNamespace(add_texts=Mock(side_effect=RuntimeError("embedding failed")))
    with pytest.raises(RuntimeError, match="embedding failed"):
        module._process_single_file(SimpleNamespace(id=701), SimpleNamespace(client=source), "idx40", vector)
    assert source.hits == before
    source.delete_by_query.assert_not_called()


def test_legacy_partial_failure_retains_es_retry_source_after_real_owner_finalize(rebuild, monkeypatch):
    monkeypatch.setattr(module, "_process_single_file", Mock(side_effect=[True, False]))
    fixtures.execute(rebuild, "document")
    rebuild.es.client.delete_by_query.assert_not_called()
    fixtures.assert_finalized(rebuild)


def test_j1_single_file_entry_reads_current_business_model_and_never_finalizes(rebuild):
    file = SimpleNamespace(id=701, tenant_id=101, knowledge_id=40)
    rebuild.file_dao.query_by_id_sync.return_value = file
    rebuild.vector.col.delete = Mock()
    assert module.rebuild_processing_file(701, space_id=40, invoke_user_id=987, **rebuild.arguments)
    assert ("provider", 12, 987) in rebuild.events
    rebuild.vector.col.drop.assert_not_called()
    rebuild.vector.col.delete.assert_called_once_with("document_id == 701 && knowledge_id == 40")
    fixtures.assert_stage_preserved(rebuild)


def test_j1_file_entry_requires_actual_worker_proof_before_io(rebuild):
    workers.reset_tenant_context(sender=rebuild.sender)
    with pytest.raises(ResourceReferenceInvalidError):
        module.rebuild_processing_file(701, space_id=40, invoke_user_id=987, **rebuild.arguments)
    assert rebuild.events == []
