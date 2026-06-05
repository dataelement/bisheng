from unittest.mock import MagicMock

from bisheng.worker.knowledge.scheduler import FileScheduler, run_dispatch_round, trigger_dispatch_task


def _conf(**overrides):
    """Build a fair-scheduler conf stub with the new capacity/weight API."""
    cap = overrides.pop("queue_concurrency", {"knowledge_celery": 20, "ocr_celery": 5})
    weights = overrides.pop("user_overrides", {})
    default_weight = overrides.pop("per_user_pick_size", 1)
    conf = MagicMock()
    conf.dispatch_lock_ttl_seconds = overrides.pop("dispatch_lock_ttl_seconds", 24)
    conf.concurrency_for = lambda q: cap.get(q, default_weight)
    conf.weight_for = lambda u: weights.get(str(u), default_weight)
    return conf


def _sched():
    """A FileScheduler stub with the new methods used by run_dispatch_round."""
    sched = MagicMock(spec=FileScheduler)
    sched.acquire_dispatch_lock.return_value = "tok"
    sched.inflight_count.return_value = 0
    sched.inflight_total.return_value = 0
    return sched


def test_single_user_backfills_until_queue_capacity(monkeypatch):
    """One user with plenty of files fills the whole queue (no per-user ceiling)."""
    sched = _sched()
    sched.active_users.return_value = ["a"]
    # user a has unlimited files; dispatch_one always returns a fresh id
    counter = {"n": 0}

    def _pop(*, user_id):
        counter["n"] += 1
        return str(counter["n"])

    sched.dispatch_one.side_effect = _pop
    sched.get_payload.side_effect = lambda *, file_id: {
        "preview_cache_key": "pk",
        "callback_url": "",
        "file_ext": "txt",
    }
    apply_async = MagicMock()
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler._parse_apply_async", apply_async)
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler.decide_queue", lambda ext: "knowledge_celery")
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler._fair_scheduler_conf",
        lambda: _conf(queue_concurrency={"knowledge_celery": 5}),
    )

    run_dispatch_round(scheduler=sched)

    # filled exactly to capacity 5, single user
    assert apply_async.call_count == 5
    assert sched.confirm_dispatch.call_count == 5
    sched.confirm_dispatch.assert_any_call(file_id="1", queue="knowledge_celery")


def test_fair_share_across_users_least_inflight_first(monkeypatch):
    """A=10, B=50, C=2, cap=20 → in-flight ends A=9, B=9, C=2 (least-inflight RR)."""
    sched = _sched()
    sched.active_users.return_value = ["A", "B", "C"]
    queues = {"A": list(range(100, 110)), "B": list(range(200, 250)), "C": list(range(300, 302))}
    # local in-flight share tracking on the stub side
    inflight = {"A": 0, "B": 0, "C": 0}
    owner = {}

    def _pop(*, user_id):
        q = queues[user_id]
        if not q:
            return None
        fid = str(q.pop(0))
        inflight[user_id] += 1
        owner[fid] = user_id
        return fid

    sched.dispatch_one.side_effect = _pop
    # in-flight share = confirmed files only; rolled-back pops don't count
    confirmed = {"A": 0, "B": 0, "C": 0}
    sched.inflight_count.side_effect = lambda *, user_id: confirmed[user_id]
    sched.confirm_dispatch.side_effect = lambda *, file_id, queue: confirmed.__setitem__(
        owner[file_id], confirmed[owner[file_id]] + 1
    )
    sched.get_payload.side_effect = lambda *, file_id: {
        "preview_cache_key": "",
        "callback_url": "",
        "file_ext": "txt",
    }
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler._parse_apply_async", MagicMock())
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler.decide_queue", lambda ext: "knowledge_celery")
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler._fair_scheduler_conf",
        lambda: _conf(queue_concurrency={"knowledge_celery": 20}),
    )

    run_dispatch_round(scheduler=sched)

    assert confirmed == {"A": 9, "B": 9, "C": 2}
    assert sched.confirm_dispatch.call_count == 20


def test_freed_slot_goes_to_least_inflight_user_not_longest_queue(monkeypatch):
    """D3: with A and B both in flight and one slot free, the slot must go to
    whoever currently holds fewer slots — NOT to the user with the longest
    queue. Here B is one below A, so the single free slot must go to B."""
    sched = _sched()
    sched.active_users.return_value = ["A", "B"]
    # A holds 10 in flight, B holds 9 → 19 of 20; exactly one slot is free.
    base = {"A": 10, "B": 9}
    sched.inflight_count.side_effect = lambda *, user_id: base[user_id]
    sched.inflight_total.side_effect = lambda *, queue: 19
    owner = {}
    seq = {"n": 0}

    def _pop(*, user_id):
        seq["n"] += 1
        fid = str(seq["n"])
        owner[fid] = user_id
        return fid

    confirmed = []
    sched.dispatch_one.side_effect = _pop
    sched.get_payload.side_effect = lambda *, file_id: {"file_ext": "txt"}
    sched.confirm_dispatch.side_effect = lambda *, file_id, queue: confirmed.append(owner[file_id])
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler._parse_apply_async", MagicMock())
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler.decide_queue", lambda ext: "knowledge_celery")
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler._fair_scheduler_conf",
        lambda: _conf(queue_concurrency={"knowledge_celery": 20}),
    )

    run_dispatch_round(scheduler=sched)

    # Only the single free slot is filled, and it goes to the starved user B.
    assert confirmed == ["B"]


def test_weighted_user_gets_proportionally_more(monkeypatch):
    """user 1 weight 3 vs user 2 weight 1, cap 20 → ~15:5 (3:1)."""
    sched = _sched()
    sched.active_users.return_value = ["1", "2"]
    seq = {"n": 0}
    owner = {}

    def _pop(*, user_id):
        seq["n"] += 1
        fid = str(seq["n"])
        owner[fid] = user_id
        return fid

    confirmed = {"1": 0, "2": 0}
    sched.dispatch_one.side_effect = _pop
    sched.inflight_count.side_effect = lambda *, user_id: confirmed[user_id]
    sched.confirm_dispatch.side_effect = lambda *, file_id, queue: confirmed.__setitem__(
        owner[file_id], confirmed[owner[file_id]] + 1
    )
    sched.get_payload.side_effect = lambda *, file_id: {"file_ext": "txt"}
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler._parse_apply_async", MagicMock())
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler.decide_queue", lambda ext: "knowledge_celery")
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler._fair_scheduler_conf",
        lambda: _conf(queue_concurrency={"knowledge_celery": 20}, user_overrides={"1": 3}),
    )

    run_dispatch_round(scheduler=sched)

    assert confirmed["1"] == 15
    assert confirmed["2"] == 5


def test_ocr_and_normal_queues_capped_independently(monkeypatch):
    """OCR files and normal files fill their own queue caps independently.

    User P uploads only PDFs (→ ocr_celery, cap 3), user T only TXT
    (→ knowledge_celery, cap 5). Each queue fills to its own cap; one
    saturating does not block the other.
    """
    sched = _sched()
    sched.active_users.return_value = ["P", "T"]
    ext_by_user = {"P": "pdf", "T": "txt"}
    seq = {"n": 0}
    owner = {}

    def _pop(*, user_id):
        seq["n"] += 1
        fid = str(seq["n"])
        owner[fid] = user_id
        return fid

    confirmed_share = {"P": 0, "T": 0}
    confirmed_queues = []
    sched.dispatch_one.side_effect = _pop
    sched.inflight_count.side_effect = lambda *, user_id: confirmed_share[user_id]
    sched.get_payload.side_effect = lambda *, file_id: {"file_ext": ext_by_user[owner[file_id]]}

    def _confirm(*, file_id, queue):
        confirmed_share[owner[file_id]] += 1
        confirmed_queues.append(queue)

    sched.confirm_dispatch.side_effect = _confirm
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler._parse_apply_async", MagicMock())
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler.decide_queue",
        lambda ext: "ocr_celery" if ext == "pdf" else "knowledge_celery",
    )
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler._fair_scheduler_conf",
        lambda: _conf(queue_concurrency={"knowledge_celery": 5, "ocr_celery": 3}),
    )

    run_dispatch_round(scheduler=sched)

    assert confirmed_queues.count("ocr_celery") == 3
    assert confirmed_queues.count("knowledge_celery") == 5


def test_saturated_queue_rolls_back_and_skips_user_no_infinite_loop(monkeypatch):
    """When a user's head file targets a full queue, it is rolled back once and the user skipped."""
    sched = _sched()
    sched.active_users.return_value = ["a"]
    sched.inflight_total.side_effect = lambda *, queue: 3 if queue == "ocr_celery" else 0
    sched.dispatch_one.side_effect = ["100", None]
    sched.get_payload.return_value = {"file_ext": "png"}  # → ocr_celery (full)
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler._parse_apply_async", MagicMock())
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler.decide_queue", lambda ext: "ocr_celery")
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler._fair_scheduler_conf",
        lambda: _conf(queue_concurrency={"ocr_celery": 3}),
    )

    run_dispatch_round(scheduler=sched)

    sched.rollback_dispatch.assert_called_once_with(user_id="a", file_id="100")
    sched.confirm_dispatch.assert_not_called()
    sched.release_dispatch_lock.assert_called_once_with("tok")


def test_rollback_on_apply_async_failure(monkeypatch):
    sched = _sched()
    sched.active_users.return_value = ["a"]
    sched.dispatch_one.side_effect = ["10", None]
    sched.get_payload.return_value = {"preview_cache_key": "pk", "callback_url": "", "file_ext": "txt"}
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler._parse_apply_async",
        MagicMock(side_effect=RuntimeError("broker down")),
    )
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler.decide_queue", lambda ext: "knowledge_celery")
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler._fair_scheduler_conf", lambda: _conf())

    run_dispatch_round(scheduler=sched)

    sched.rollback_dispatch.assert_called_once_with(user_id="a", file_id="10")
    sched.confirm_dispatch.assert_not_called()
    sched.release_dispatch_lock.assert_called_once_with("tok")


def test_no_lock_returns_early(monkeypatch):
    sched = _sched()
    sched.acquire_dispatch_lock.return_value = None
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler._fair_scheduler_conf", lambda: _conf())

    run_dispatch_round(scheduler=sched)

    sched.active_users.assert_not_called()
    sched.release_dispatch_lock.assert_not_called()


def test_missing_payload_rolls_back(monkeypatch):
    sched = _sched()
    sched.active_users.return_value = ["a"]
    sched.dispatch_one.side_effect = ["10", None]
    sched.get_payload.return_value = {}  # evicted
    apply_async = MagicMock()
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler._parse_apply_async", apply_async)
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler._fair_scheduler_conf", lambda: _conf())

    run_dispatch_round(scheduler=sched)

    apply_async.assert_not_called()
    sched.rollback_dispatch.assert_called_once_with(user_id="a", file_id="10")
    sched.release_dispatch_lock.assert_called_once_with("tok")


def test_stamps_owning_tenant(monkeypatch):
    """The dispatched parse task must run under the file's OWNING tenant."""
    from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id

    sched = _sched()
    sched.active_users.return_value = ["a"]
    sched.dispatch_one.side_effect = ["10", None]
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
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler.decide_queue", lambda ext: "knowledge_celery")
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler._fair_scheduler_conf", lambda: _conf())

    set_current_tenant_id(1)
    run_dispatch_round(scheduler=sched)

    assert seen["tenant"] == 18
    assert current_tenant_id.get() == 1


def test_trigger_dispatch_task_returns_early_when_fair_disabled(monkeypatch):
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler._fair_scheduler_enabled", lambda: False)
    run_round = MagicMock()
    monkeypatch.setattr("bisheng.worker.knowledge.scheduler.run_dispatch_round", run_round)
    trigger_dispatch_task.run()
    run_round.assert_not_called()
