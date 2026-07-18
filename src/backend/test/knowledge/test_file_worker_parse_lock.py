"""Per-file parse idempotency lock.

A file must never be parsed by two workers at once. Duplicates can arrive via
``acks_late`` broker redelivery (worker OOM-killed mid-parse) or a reconcile
re-enqueue of a file that is still being parsed. Without a guard, N threads
load the same large file + LLM + Milvus/ES at once and blow up memory — the
"task storm" OOM loop. The parse task must grab a per-file lock first and skip
entirely when it can't.
"""

from unittest.mock import MagicMock

import pytest

from bisheng.worker.knowledge import file_worker


@pytest.fixture(autouse=True)
def _fair_enabled(monkeypatch):
    monkeypatch.setattr(
        "bisheng.common.services.config_service.settings.knowledge_file_worker.fair_scheduler_enabled",
        True,
    )
    # Keep the heartbeat thread from doing anything real in unit tests.
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler.start_parse_heartbeat",
        lambda *a, **kw: lambda: None,
    )
    yield


def test_duplicate_parse_skipped_when_lock_held(monkeypatch):
    """When the parse lock can't be acquired (another worker holds it) the task
    must NOT parse and must NOT touch the scheduler completion bookkeeping."""
    parse = MagicMock()
    monkeypatch.setattr(file_worker, "_parse_knowledge_file", parse)

    complete = MagicMock()
    release = MagicMock()
    trigger = MagicMock()
    sched = MagicMock()
    sched.acquire_parse_lock.return_value = None  # someone else is parsing
    sched.complete_file = complete
    sched.release_file = release
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler.FileScheduler", lambda: sched)
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler.trigger_dispatch_task",
        MagicMock(delay=trigger),
    )

    file_worker.parse_knowledge_file_celery.run(3684)

    parse.assert_not_called()
    complete.assert_not_called()
    release.assert_not_called()
    trigger.assert_not_called()


def test_parse_lock_released_after_parse(monkeypatch):
    """A successful parse must release the lock it acquired (token-checked)."""
    monkeypatch.setattr(file_worker, "_parse_knowledge_file", lambda *a, **kw: MagicMock())
    monkeypatch.setattr(file_worker, "delete_vector_files", MagicMock())

    db_file = MagicMock(user_id=42)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge_file.KnowledgeFileDao.get_file_by_ids",
        lambda ids: [db_file],
    )

    sched = MagicMock()
    sched.acquire_parse_lock.return_value = "tok-123"
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler.FileScheduler", lambda: sched)
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler.trigger_dispatch_task",
        MagicMock(delay=MagicMock()),
    )

    file_worker.parse_knowledge_file_celery.run(100)

    sched.complete_file.assert_called_once_with(user_id="42", file_id="100")
    sched.release_parse_lock.assert_called_once_with(file_id="100", token="tok-123")
