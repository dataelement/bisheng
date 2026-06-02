from unittest.mock import MagicMock

from bisheng.worker.knowledge.scheduler import FileScheduler, run_dispatch_round, trigger_dispatch_task


def test_run_dispatch_round_dispatches_one_file_per_active_user(monkeypatch):
    sched = MagicMock(spec=FileScheduler)
    sched.acquire_dispatch_lock.return_value = "tok"
    sched.active_users.return_value = ["a", "b"]
    sched.dispatch_one.side_effect = ["10", "20"]
    sched.get_payload.side_effect = [
        {"preview_cache_key": "pk1", "callback_url": "cb", "file_ext": "txt"},
        {"preview_cache_key": "pk2", "callback_url": "", "file_ext": "pdf"},
    ]
    apply_async = MagicMock()
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler._parse_apply_async", apply_async)
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler.decide_queue",
        lambda ext: "knowledge_celery",
    )
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler._fair_scheduler_conf",
        lambda: MagicMock(dispatch_lock_ttl_seconds=24, limit_for=lambda _u: 1),
    )

    run_dispatch_round(scheduler=sched)

    assert apply_async.call_count == 2
    apply_async.assert_any_call(args=[10, "pk1", "cb"], queue="knowledge_celery")
    apply_async.assert_any_call(args=[20, "pk2", ""], queue="knowledge_celery")
    sched.delete_payload.assert_any_call(file_id="10")
    sched.delete_payload.assert_any_call(file_id="20")
    sched.release_dispatch_lock.assert_called_once_with("tok")


def test_run_dispatch_round_rollback_on_apply_async_failure(monkeypatch):
    sched = MagicMock(spec=FileScheduler)
    sched.acquire_dispatch_lock.return_value = "tok"
    sched.active_users.return_value = ["a"]
    sched.dispatch_one.return_value = "10"
    sched.get_payload.return_value = {
        "preview_cache_key": "pk",
        "callback_url": "",
        "file_ext": "txt",
    }
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler._parse_apply_async",
        MagicMock(side_effect=RuntimeError("broker down")),
    )
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler.decide_queue",
        lambda ext: "knowledge_celery",
    )
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler._fair_scheduler_conf",
        lambda: MagicMock(dispatch_lock_ttl_seconds=24, limit_for=lambda _u: 1),
    )

    run_dispatch_round(scheduler=sched)

    sched.rollback_dispatch.assert_called_once_with(user_id="a", file_id="10")
    sched.delete_payload.assert_not_called()
    sched.release_dispatch_lock.assert_called_once_with("tok")


def test_run_dispatch_round_no_lock_returns_early(monkeypatch):
    sched = MagicMock(spec=FileScheduler)
    sched.acquire_dispatch_lock.return_value = None
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler._fair_scheduler_conf",
        lambda: MagicMock(dispatch_lock_ttl_seconds=24, limit_for=lambda _u: 1),
    )

    run_dispatch_round(scheduler=sched)

    sched.active_users.assert_not_called()
    sched.release_dispatch_lock.assert_not_called()


def test_run_dispatch_round_missing_payload_rolls_back(monkeypatch):
    sched = MagicMock(spec=FileScheduler)
    sched.acquire_dispatch_lock.return_value = "tok"
    sched.active_users.return_value = ["a"]
    sched.dispatch_one.return_value = "10"
    sched.get_payload.return_value = {}  # evicted
    apply_async = MagicMock()
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler._parse_apply_async", apply_async)
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler._fair_scheduler_conf",
        lambda: MagicMock(dispatch_lock_ttl_seconds=24, limit_for=lambda _u: 1),
    )

    run_dispatch_round(scheduler=sched)

    apply_async.assert_not_called()
    sched.rollback_dispatch.assert_called_once_with(user_id="a", file_id="10")
    sched.release_dispatch_lock.assert_called_once_with("tok")


def test_run_dispatch_round_stamps_owning_tenant(monkeypatch):
    """The dispatched parse task must run under the file's OWNING tenant
    (from payload), not the tenant driving the dispatch round."""
    from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id

    sched = MagicMock(spec=FileScheduler)
    sched.acquire_dispatch_lock.return_value = "tok"
    sched.active_users.return_value = ["a"]
    sched.dispatch_one.return_value = "10"
    sched.get_payload.return_value = {
        "preview_cache_key": "pk",
        "callback_url": "",
        "file_ext": "txt",
        "tenant_id": "18",
    }
    seen = {}

    def _capture(*, args, queue):
        seen["tenant"] = current_tenant_id.get()

    monkeypatch.setattr("bisheng.worker.knowledge.scheduler._parse_apply_async", _capture)
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler.decide_queue",
        lambda ext: "knowledge_celery",
    )
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler._fair_scheduler_conf",
        lambda: MagicMock(dispatch_lock_ttl_seconds=24, limit_for=lambda _u: 1),
    )

    # Simulate a Beat-driven round running under the default tenant (1).
    set_current_tenant_id(1)
    run_dispatch_round(scheduler=sched)

    assert seen["tenant"] == 18  # stamped with the file's owning tenant
    # context restored to the round's tenant afterwards
    assert current_tenant_id.get() == 1


def test_trigger_dispatch_task_returns_early_when_fair_disabled(monkeypatch):
    """When fair_scheduler_enabled=False the Beat task must not call run_dispatch_round."""
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler._fair_scheduler_enabled",
        lambda: False,
    )
    run_round = MagicMock()
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler.run_dispatch_round", run_round)
    trigger_dispatch_task.run()
    run_round.assert_not_called()
