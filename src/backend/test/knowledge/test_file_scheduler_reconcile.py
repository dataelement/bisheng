from datetime import datetime, timedelta
from unittest.mock import MagicMock

from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileStatus
from bisheng.worker.knowledge.scheduler import reconcile_file_scheduler_task


def _row(status, file_name="a.txt", user_id=1, update_time=None):
    m = MagicMock()
    m.status = status.value if hasattr(status, "value") else status
    m.file_name = file_name
    m.user_id = user_id
    m.update_time = update_time or datetime.now()
    return m


def _patch_fair_enabled(monkeypatch):
    """Patch _fair_scheduler_enabled to return True so the task body runs."""
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler._fair_scheduler_enabled",
        lambda: True,
    )


def test_case1_done_in_db_clears_inflight(monkeypatch):
    _patch_fair_enabled(monkeypatch)
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
    _patch_fair_enabled(monkeypatch)
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
    _patch_fair_enabled(monkeypatch)
    sched = MagicMock()
    sched.inflight_users.return_value = ["7"]
    sched.inflight_files.return_value = ["100"]
    sched.active_users.return_value = []
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler.FileScheduler", lambda: sched)
    stale = datetime.now() - timedelta(hours=10)
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
    _patch_fair_enabled(monkeypatch)
    sched = MagicMock()
    sched.inflight_users.return_value = ["7"]
    sched.inflight_files.return_value = ["100"]
    sched.active_users.return_value = []
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler.FileScheduler", lambda: sched)
    fresh = datetime.now()
    row = _row(KnowledgeFileStatus.PROCESSING, update_time=fresh)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge_file.KnowledgeFileDao.get_file_by_ids",
        lambda ids: [row],
    )

    reconcile_file_scheduler_task.run()

    sched.complete_file.assert_not_called()
    sched.enqueue_file.assert_not_called()


def test_case_missing_row_clears_inflight(monkeypatch):
    _patch_fair_enabled(monkeypatch)
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


def test_case1_timeout_status_is_treated_as_terminal(monkeypatch):
    _patch_fair_enabled(monkeypatch)
    sched = MagicMock()
    sched.inflight_users.return_value = ["7"]
    sched.inflight_files.return_value = ["100"]
    sched.active_users.return_value = []
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler.FileScheduler", lambda: sched)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge_file.KnowledgeFileDao.get_file_by_ids",
        lambda ids: [_row(KnowledgeFileStatus.TIMEOUT)],
    )

    reconcile_file_scheduler_task.run()

    sched.complete_file.assert_called_once_with(user_id="7", file_id="100")
    sched.enqueue_file.assert_not_called()


def test_case4_drained_active_user_removed(monkeypatch):
    """If queue and inflight are both empty, user must be removed from active_users."""
    _patch_fair_enabled(monkeypatch)
    fake_conn = MagicMock()
    fake_conn.llen.return_value = 0
    fake_conn.scard.return_value = 0
    sched = MagicMock()
    sched.inflight_users.return_value = []  # no inflight to reconcile
    sched.active_users.return_value = ["9"]
    sched._conn = fake_conn
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler.FileScheduler", lambda: sched)

    reconcile_file_scheduler_task.run()

    # Must SREM user from active_users
    fake_conn.srem.assert_called_once()
    args, _ = fake_conn.srem.call_args
    assert args[0] == "{bisheng_fs}:active_users"
    assert args[1] == "9"


def test_case4_user_with_queued_files_not_removed(monkeypatch):
    _patch_fair_enabled(monkeypatch)
    fake_conn = MagicMock()
    fake_conn.llen.return_value = 3  # files still queued
    fake_conn.scard.return_value = 0
    sched = MagicMock()
    sched.inflight_users.return_value = []
    sched.active_users.return_value = ["9"]
    sched._conn = fake_conn
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler.FileScheduler", lambda: sched)

    reconcile_file_scheduler_task.run()

    fake_conn.srem.assert_not_called()


def test_reconcile_task_returns_early_when_fair_disabled(monkeypatch):
    """When fair_scheduler_enabled=False the Beat task must not instantiate FileScheduler."""
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler._fair_scheduler_enabled",
        lambda: False,
    )
    scheduler_cls = MagicMock()
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler.FileScheduler", scheduler_cls)
    reconcile_file_scheduler_task.run()
    scheduler_cls.assert_not_called()
