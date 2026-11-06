"""Completed partial rebuilds stay usable; incomplete global failures do not.

The original per-file availability regression is retained with an actual
business transition, full-source admission and atomic SQL/R2 finalization.
The retired global-error forced-PUBLISHED behavior would erase an unfinished
pending stage; failures now preserve it for an explicit recovery operation.
No provider, vectorstore, queue or deployed database is contacted.
"""

from types import SimpleNamespace
from unittest.mock import Mock

from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError
from bisheng.knowledge.domain.models.knowledge import KnowledgeState
from bisheng.worker.knowledge import rebuild_knowledge_worker as worker
from test.knowledge_unification import test_kn_model_bindings as business_fixtures
from test.knowledge_unification import test_kn_worker_model_source as fixtures

store = fixtures.store
tenant = fixtures.tenant
business = fixtures.business
admission = fixtures.admission
rebuild = fixtures.rebuild


def _run(rebuild, monkeypatch, *, success, failed, raise_on_rebuild=None):
    files = [SimpleNamespace(id=file_id, status=2, remark=None) for file_id in (*success, *failed)]
    rebuild.file_dao.get_files_by_multiple_status.side_effect = lambda *args: files

    def process(*args, **kwargs):
        if raise_on_rebuild is not None:
            raise raise_on_rebuild
        return list(success), list(failed)

    monkeypatch.setattr(worker, "_rebuild_embeddings", process)
    monkeypatch.setattr(worker, "_delete_es_files", Mock())
    try:
        fixtures.execute(rebuild, "document")
    except Exception as error:
        return files, error
    return files, None


def test_a_partly_failed_rebuild_leaves_the_container_published(rebuild, monkeypatch):
    files, error = _run(rebuild, monkeypatch, success=[1, 2], failed=[3])
    assert error is None
    fixtures.assert_finalized(rebuild)
    failed_file = next(item for item in files if item.id == 3)
    assert failed_file.status == 3 and failed_file.remark
    rebuild.file_dao.update_status_bulk.assert_any_call([1, 2], worker.KnowledgeFileStatus.SUCCESS)


def test_an_unexpected_global_error_preserves_unfinished_business_stage(rebuild, monkeypatch):
    _, error = _run(rebuild, monkeypatch, success=[1, 2], failed=[], raise_on_rebuild=RuntimeError("milvus down"))
    assert isinstance(error, RuntimeError)
    fixtures.assert_stage_preserved(rebuild)
    row = next(item for item in business_fixtures.state(rebuild.context)["knowledge"] if item["id"] == 40)
    assert row["state"] == KnowledgeState.REBUILDING.value
    assert row["model"] == "11" and row["model_transition"]["pending_model_id"] == "12"


def test_controlled_all_file_failures_do_not_write_a_container_failed_state(rebuild, monkeypatch):
    files, error = _run(rebuild, monkeypatch, success=[], failed=[1, 2])
    assert error is None
    assert all(item.status == 3 and item.remark for item in files)
    fixtures.assert_finalized(rebuild)
    row = next(item for item in business_fixtures.state(rebuild.context)["knowledge"] if item["id"] == 40)
    assert row["state"] == KnowledgeState.PUBLISHED.value
    assert row["state"] != KnowledgeState.FAILED.value


def test_reference_guard_failure_is_not_reclassified_as_a_finished_partial_run(rebuild, monkeypatch):
    _, error = _run(
        rebuild,
        monkeypatch,
        success=[1],
        failed=[],
        raise_on_rebuild=ReferenceCoverageNotReadyError(reason="source_not_ready"),
    )
    assert isinstance(error, ReferenceCoverageNotReadyError)
    fixtures.assert_stage_preserved(rebuild)
