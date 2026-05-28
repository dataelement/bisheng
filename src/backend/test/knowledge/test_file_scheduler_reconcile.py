from datetime import datetime, timedelta
from unittest.mock import MagicMock

from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileStatus
from bisheng.worker.knowledge.scheduler import reconcile_file_scheduler_task


def _row(status, file_name="a.txt", user_id=1, update_time=None):
    m = MagicMock()
    m.status = status.value if hasattr(status, "value") else status
    m.file_name = file_name
    m.user_id = user_id
    m.update_time = update_time or datetime.utcnow()
    return m


def test_case1_done_in_db_clears_inflight(monkeypatch):
    sched = MagicMock()
    sched.inflight_users.return_value = ["7"]
    sched.inflight_files.return_value = ["100"]
    sched.active_users.return_value = []
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler.FileScheduler", lambda: sched)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge_file.KnowledgeFileDao.get_file_by_ids",
        lambda ids: [_row(KnowledgeFileStatus.SUCCESS)],
    )

    reconcile_file_scheduler_task.run()

    sched.complete_file.assert_any_call(user_id="7", file_id="100")


def test_case2_still_waiting_reenqueues(monkeypatch):
    sched = MagicMock()
    sched.inflight_users.return_value = ["7"]
    sched.inflight_files.return_value = ["100"]
    sched.active_users.return_value = []
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler.FileScheduler", lambda: sched)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge_file.KnowledgeFileDao.get_file_by_ids",
        lambda ids: [_row(KnowledgeFileStatus.WAITING, file_name="img.png", user_id=7)],
    )

    reconcile_file_scheduler_task.run()

    sched.complete_file.assert_any_call(user_id="7", file_id="100")
    sched.enqueue_file.assert_called_once()


def test_case3_processing_timeout_reenqueues(monkeypatch):
    sched = MagicMock()
    sched.inflight_users.return_value = ["7"]
    sched.inflight_files.return_value = ["100"]
    sched.active_users.return_value = []
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler.FileScheduler", lambda: sched)
    stale = datetime.utcnow() - timedelta(hours=10)
    row = _row(KnowledgeFileStatus.PROCESSING, file_name="a.pdf", user_id=7, update_time=stale)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge_file.KnowledgeFileDao.get_file_by_ids",
        lambda ids: [row],
    )
    status_update = MagicMock()
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge_file.KnowledgeFileDao.update_file_status",
        status_update,
    )

    reconcile_file_scheduler_task.run()

    sched.complete_file.assert_called_once_with(user_id="7", file_id="100")
    sched.enqueue_file.assert_called_once()
    status_update.assert_called_once()


def test_case3_processing_fresh_skips(monkeypatch):
    sched = MagicMock()
    sched.inflight_users.return_value = ["7"]
    sched.inflight_files.return_value = ["100"]
    sched.active_users.return_value = []
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler.FileScheduler", lambda: sched)
    fresh = datetime.utcnow()
    row = _row(KnowledgeFileStatus.PROCESSING, update_time=fresh)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge_file.KnowledgeFileDao.get_file_by_ids",
        lambda ids: [row],
    )

    reconcile_file_scheduler_task.run()

    sched.complete_file.assert_not_called()
    sched.enqueue_file.assert_not_called()


def test_case_missing_row_clears_inflight(monkeypatch):
    sched = MagicMock()
    sched.inflight_users.return_value = ["7"]
    sched.inflight_files.return_value = ["100"]
    sched.active_users.return_value = []
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler.FileScheduler", lambda: sched)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge_file.KnowledgeFileDao.get_file_by_ids",
        lambda ids: [],
    )

    reconcile_file_scheduler_task.run()

    sched.complete_file.assert_called_once_with(user_id="7", file_id="100")
