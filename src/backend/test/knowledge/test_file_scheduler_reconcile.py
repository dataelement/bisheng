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


def test_case5_queue_ghost_removed(monkeypatch):
    """A queued file with no payload AND a terminal DB row is a ghost: reconcile
    must LREM it from the queue so it stops blocking dispatch."""
    _patch_fair_enabled(monkeypatch)
    fake_conn = MagicMock()
    fake_conn.llen.return_value = 1
    fake_conn.scard.return_value = 0
    sched = MagicMock()
    sched.inflight_users.return_value = []
    sched.active_users.return_value = ["3"]
    sched.queued_files.return_value = ["94238"]
    sched.get_payload.return_value = {}  # payload expired
    sched._conn = fake_conn
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler.FileScheduler", lambda: sched)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge_file.KnowledgeFileDao.get_file_by_ids",
        lambda ids: [_row(KnowledgeFileStatus.SUCCESS)],
    )

    reconcile_file_scheduler_task.run()

    sched.remove_from_queue.assert_called_once_with(user_id="3", file_id="94238")
    sched.put_payload.assert_not_called()


def test_case5_queue_orphan_waiting_rebuilds_payload(monkeypatch):
    """A queued file still WAITING but with an expired payload must have its
    payload rebuilt (not removed) so the next dispatch can parse it."""
    _patch_fair_enabled(monkeypatch)
    fake_conn = MagicMock()
    fake_conn.llen.return_value = 1
    fake_conn.scard.return_value = 0
    sched = MagicMock()
    sched.inflight_users.return_value = []
    sched.active_users.return_value = ["3"]
    sched.queued_files.return_value = ["555"]
    sched.get_payload.return_value = {}
    sched._conn = fake_conn
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler.FileScheduler", lambda: sched)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge_file.KnowledgeFileDao.get_file_by_ids",
        lambda ids: [_row(KnowledgeFileStatus.WAITING, file_name="x.pdf", user_id=3)],
    )

    reconcile_file_scheduler_task.run()

    sched.put_payload.assert_called_once()
    sched.remove_from_queue.assert_not_called()


def test_case5_healthy_queued_file_untouched(monkeypatch):
    """A queued file that still has its payload must be left alone."""
    _patch_fair_enabled(monkeypatch)
    fake_conn = MagicMock()
    fake_conn.llen.return_value = 1
    fake_conn.scard.return_value = 0
    sched = MagicMock()
    sched.inflight_users.return_value = []
    sched.active_users.return_value = ["3"]
    sched.queued_files.return_value = ["555"]
    sched.get_payload.return_value = {"file_ext": "txt", "user_id": "3"}
    sched._conn = fake_conn
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler.FileScheduler", lambda: sched)

    reconcile_file_scheduler_task.run()

    sched.remove_from_queue.assert_not_called()
    sched.put_payload.assert_not_called()


def test_case4_drained_active_user_removed(monkeypatch):
    """If queue and inflight are both empty, user must be removed from active_users."""
    _patch_fair_enabled(monkeypatch)
    fake_conn = MagicMock()
    fake_conn.llen.return_value = 0
    fake_conn.scard.return_value = 0
    sched = MagicMock()
    sched.inflight_users.return_value = []  # no inflight to reconcile
    sched.active_users.return_value = ["9"]
    sched.queued_files.return_value = []
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
    sched.queued_files.return_value = []
    sched._conn = fake_conn
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler.FileScheduler", lambda: sched)

    reconcile_file_scheduler_task.run()

    fake_conn.srem.assert_not_called()


def test_reconcile_recomputes_inflight_totals(monkeypatch):
    """Reconcile must authoritatively rebuild the per-queue in-flight counters
    so lost confirm/complete callbacks don't leave the counters drifting."""
    _patch_fair_enabled(monkeypatch)
    sched = MagicMock()
    sched.inflight_users.return_value = []
    sched.active_users.return_value = []
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler.FileScheduler", lambda: sched)

    reconcile_file_scheduler_task.run()

    sched.recompute_inflight_totals.assert_called_once()
    # must pass the configured queues so absent queues get reset to 0
    _, kwargs = sched.recompute_inflight_totals.call_args
    assert "knowledge_celery" in kwargs["queues"]


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
