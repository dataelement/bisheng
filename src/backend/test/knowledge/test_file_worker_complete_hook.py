from unittest.mock import MagicMock

import pytest

from bisheng.worker.knowledge import file_worker


@pytest.fixture(autouse=True)
def stub_parse(monkeypatch):
    monkeypatch.setattr(file_worker, "_parse_knowledge_file", lambda *a, **kw: MagicMock())
    # Prevent real Milvus/ES calls when the vector-cleanup branch fires.
    monkeypatch.setattr(file_worker, "delete_vector_files", MagicMock())
    yield


def test_complete_file_called_when_fair_scheduler_enabled(monkeypatch):
    monkeypatch.setattr(
        "bisheng.common.services.config_service.settings.knowledge_file_worker.fair_scheduler_enabled",
        True,
    )
    db_file = MagicMock(user_id=42)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge_file.KnowledgeFileDao.get_file_by_ids",
        lambda ids: [db_file],
    )
    complete = MagicMock()
    trigger = MagicMock()
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler.FileScheduler",
        lambda: MagicMock(complete_file=complete),
    )
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler.trigger_dispatch_task",
        MagicMock(delay=trigger),
    )

    file_worker.parse_knowledge_file_celery.run(100)

    complete.assert_called_once_with(user_id="42", file_id="100")
    trigger.assert_called_once_with()


def test_complete_file_skipped_when_fair_scheduler_disabled(monkeypatch):
    monkeypatch.setattr(
        "bisheng.common.services.config_service.settings.knowledge_file_worker.fair_scheduler_enabled",
        False,
    )
    db_file = MagicMock(user_id=42)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge_file.KnowledgeFileDao.get_file_by_ids",
        lambda ids: [db_file],
    )
    sched_factory = MagicMock()
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler.FileScheduler", sched_factory)

    file_worker.parse_knowledge_file_celery.run(100)

    sched_factory.assert_not_called()


def test_complete_file_safe_when_db_row_missing(monkeypatch):
    monkeypatch.setattr(
        "bisheng.common.services.config_service.settings.knowledge_file_worker.fair_scheduler_enabled",
        True,
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge_file.KnowledgeFileDao.get_file_by_ids",
        lambda ids: [],
    )
    sched_factory = MagicMock()
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler.FileScheduler", sched_factory)

    file_worker.parse_knowledge_file_celery.run(100)  # must not raise

    sched_factory.assert_not_called()
