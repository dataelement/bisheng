from unittest.mock import MagicMock

from bisheng.worker.knowledge.scheduler import enqueue_or_dispatch


def test_fair_off_uses_direct_apply_async(monkeypatch):
    apply_async = MagicMock()
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler._parse_apply_async", apply_async)
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler._fair_scheduler_enabled", lambda: False)
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler.decide_queue", lambda name: "ocr_celery")

    enqueue_or_dispatch(
        user_id=7,
        file_id=42,
        file_name="a.pdf",
        preview_cache_key="pk",
        callback_url="cb",
    )

    apply_async.assert_called_once_with(args=[42, "pk", "cb"], queue="ocr_celery")


def test_fair_on_calls_enqueue_and_trigger(monkeypatch):
    sched = MagicMock()
    trigger = MagicMock()
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler.FileScheduler", lambda: sched)
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler._fair_scheduler_enabled", lambda: True)
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler.trigger_dispatch_task",
        MagicMock(delay=trigger),
    )

    enqueue_or_dispatch(
        user_id=7,
        file_id=42,
        file_name="a.pdf",
        preview_cache_key="pk",
        callback_url="cb",
    )

    sched.enqueue_file.assert_called_once_with(
        user_id="7",
        file_id="42",
        preview_cache_key="pk",
        callback_url="cb",
        file_ext="pdf",
    )
    trigger.assert_called_once_with()


def test_fair_on_swallows_trigger_failure(monkeypatch):
    sched = MagicMock()
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler.FileScheduler", lambda: sched)
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler._fair_scheduler_enabled", lambda: True)
    fake_task = MagicMock()
    fake_task.delay.side_effect = RuntimeError("broker hiccup")
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler.trigger_dispatch_task", fake_task)

    # Should not raise — file is safely enqueued; Beat will pick it up.
    enqueue_or_dispatch(
        user_id=7,
        file_id=42,
        file_name="x.txt",
        preview_cache_key="",
        callback_url="",
    )
    sched.enqueue_file.assert_called_once()
