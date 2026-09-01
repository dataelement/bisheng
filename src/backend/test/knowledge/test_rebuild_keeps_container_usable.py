"""A failed file must not take its knowledge container down with it.

The rebuild worker used to mark the whole knowledge FAILED as soon as one file
failed. That flag existed to drive a later automatic rebuild, which no longer
happens — a failed file is recovered by re-parsing it. Meanwhile permission
target resolution requires the container to be PUBLISHED, so the flag made a
whole knowledge space unreachable and reported it as "invalid resource type or
ID". Twenty-one spaces were stranded that way.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from bisheng.knowledge.domain.models.knowledge import KnowledgeState

_WORKER = "bisheng.worker.knowledge.rebuild_knowledge_worker"


@pytest.fixture
def knowledge():
    return SimpleNamespace(id=4149, state=KnowledgeState.REBUILDING.value, model=7)


def _run(knowledge, *, success, failed, raise_on_rebuild=None):
    files = [SimpleNamespace(id=file_id, status=0, remark=None) for file_id in (*success, *failed)]
    saved: list[object] = []

    def rebuild(*args, **kwargs):
        del args, kwargs
        if raise_on_rebuild is not None:
            raise raise_on_rebuild
        return list(success), list(failed)

    with (
        patch(f"{_WORKER}.KnowledgeDao") as dao,
        patch(f"{_WORKER}.KnowledgeFileDao") as file_dao,
        patch(f"{_WORKER}._rebuild_embeddings", side_effect=rebuild),
        patch(f"{_WORKER}._delete_es_files"),
        patch(f"{_WORKER}.KnowledgeService"),
    ):
        dao.query_by_id.return_value = knowledge
        dao.update_one.side_effect = lambda row: saved.append(row)
        file_dao.get_files_by_multiple_status.return_value = files

        from bisheng.worker.knowledge import rebuild_knowledge_worker

        try:
            rebuild_knowledge_worker.rebuild_knowledge_celery.run(knowledge.id, 9, 1)
        except Exception as exc:  # surfaced to Celery; state must still be sane
            return files, exc
    return files, None


def test_a_partly_failed_rebuild_leaves_the_container_published(knowledge) -> None:
    files, error = _run(knowledge, success=[1, 2], failed=[3])

    assert error is None
    assert knowledge.state == KnowledgeState.PUBLISHED.value
    # The failure is recorded where it actually happened.
    failed_file = next(item for item in files if item.id == 3)
    assert failed_file.status == 3


def test_an_unexpected_error_does_not_strand_the_container(knowledge) -> None:
    # Needs files, otherwise the worker returns before it ever rebuilds.
    files, error = _run(knowledge, success=[1, 2], failed=[], raise_on_rebuild=RuntimeError("milvus down"))

    del files
    assert isinstance(error, RuntimeError)
    # Neither FAILED nor stuck in REBUILDING.
    assert knowledge.state == KnowledgeState.PUBLISHED.value


def test_the_worker_no_longer_writes_a_container_failed_state() -> None:
    """Guard the intent itself, not just the two paths exercised above."""

    from pathlib import Path

    source = Path(f"bisheng/worker/knowledge/{'rebuild_knowledge_worker'}.py").read_text(encoding="utf-8")
    assert "KnowledgeState.FAILED" not in source
