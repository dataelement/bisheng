from unittest.mock import MagicMock

from bisheng.worker.knowledge import file_worker


def test_retry_legacy_path_still_parses_inline(monkeypatch):
    monkeypatch.setattr(
        "bisheng.common.services.config_service.settings.knowledge_file_worker.fair_scheduler_enabled",
        False,
    )
    monkeypatch.setattr(file_worker, "delete_knowledge_file_vectors", MagicMock())
    parse = MagicMock(return_value=MagicMock())
    monkeypatch.setattr(file_worker, "_parse_knowledge_file", parse)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge_file.KnowledgeFileDao.get_file_by_ids",
        lambda ids: [MagicMock(user_id=1)],
    )

    file_worker.retry_knowledge_file_celery.run(99)

    parse.assert_called_once_with(99, None, None)


def test_retry_fair_path_reenqueues_after_cleanup(monkeypatch):
    monkeypatch.setattr(
        "bisheng.common.services.config_service.settings.knowledge_file_worker.fair_scheduler_enabled",
        True,
    )
    cleanup = MagicMock()
    monkeypatch.setattr(file_worker, "delete_knowledge_file_vectors", cleanup)
    parse = MagicMock()
    monkeypatch.setattr(file_worker, "_parse_knowledge_file", parse)

    db_row = MagicMock(user_id=11, file_name="a.pdf")
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge_file.KnowledgeFileDao.get_file_by_ids",
        lambda ids: [db_row],
    )
    status_update = MagicMock()
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge_file.KnowledgeFileDao.update_file_status",
        status_update,
    )

    enqueue = MagicMock()
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler.enqueue_or_dispatch", enqueue)

    file_worker.retry_knowledge_file_celery.run(99, "pk", "cb")

    cleanup.assert_called_once_with(file_ids=[99], clear_minio=False)
    parse.assert_not_called()  # parsing now happens via dispatched task
    enqueue.assert_called_once_with(
        user_id=11,
        file_id=99,
        file_name="a.pdf",
        preview_cache_key="pk",
        callback_url="cb",
    )


def test_retry_fair_path_cleanup_failure_marks_failed(monkeypatch):
    monkeypatch.setattr(
        "bisheng.common.services.config_service.settings.knowledge_file_worker.fair_scheduler_enabled",
        True,
    )
    monkeypatch.setattr(
        file_worker,
        "delete_knowledge_file_vectors",
        MagicMock(side_effect=RuntimeError("milvus down")),
    )
    status_update = MagicMock()
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge_file.KnowledgeFileDao.update_file_status",
        status_update,
    )

    file_worker.retry_knowledge_file_celery.run(99)

    # update_file_status called with FAILED + remark
    assert status_update.called
    args, _ = status_update.call_args
    assert args[0] == [99]
