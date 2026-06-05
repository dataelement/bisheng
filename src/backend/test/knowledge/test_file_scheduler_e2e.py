import socket
from unittest.mock import MagicMock
from urllib.parse import urlparse

import pytest
import redis

from bisheng.common.services.config_service import settings
from bisheng.worker.knowledge import scheduler as s

_parsed = urlparse(settings.redis_url)
REDIS_HOST = _parsed.hostname or "localhost"
REDIS_PORT = _parsed.port or 6379
REDIS_TEST_DB = 15


def _redis_reachable():
    try:
        with socket.create_connection((REDIS_HOST, REDIS_PORT), timeout=0.5):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _redis_reachable(), reason="needs Redis")


def _conf(cap, **overrides):
    """Fair-scheduler conf stub with the new capacity/weight API."""
    conf = MagicMock()
    conf.dispatch_lock_ttl_seconds = 24
    conf.queue_concurrency = {"knowledge_celery": cap}
    conf.concurrency_for = lambda q: cap
    conf.weight_for = lambda u: overrides.get("weights", {}).get(str(u), 1)
    return conf


@pytest.fixture
def redis_conn():
    conn = redis.StrictRedis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_TEST_DB, decode_responses=True)
    for k in conn.keys("{bisheng_fs}:*"):
        conn.delete(k)
    yield conn
    for k in conn.keys("{bisheng_fs}:*"):
        conn.delete(k)


_RealFileScheduler = s.FileScheduler


def _make_scheduler_factory(redis_conn):
    """Return a callable that creates a FileScheduler backed by redis_conn.

    Accepts and ignores any keyword arguments so it works whether called as
    ``FileScheduler()`` (from the module functions) or as
    ``FileScheduler(connection=...)`` (from test helpers that haven't been
    patched yet when they run).
    """

    def _factory(**kwargs):
        return _RealFileScheduler(connection=redis_conn)

    return _factory


def test_round_trip_two_files_one_user(redis_conn, monkeypatch):
    # Patch FileScheduler() (no-arg form used by enqueue_or_dispatch / run_dispatch_round)
    # to inject the real Redis connection instead of going through RedisManager.
    monkeypatch.setattr(s, "FileScheduler", _make_scheduler_factory(redis_conn))

    apply_async = MagicMock()
    monkeypatch.setattr(s, "_parse_apply_async", apply_async)
    monkeypatch.setattr(s, "decide_queue", lambda name: "knowledge_celery")
    monkeypatch.setattr(s, "_fair_scheduler_enabled", lambda: True)
    # Queue capacity 1 → only one file can be in flight at a time.
    monkeypatch.setattr(s, "_fair_scheduler_conf", lambda: _conf(cap=1))
    # The enqueue path calls trigger_dispatch_task.delay() — make it a no-op
    # for this test; we drive run_dispatch_round explicitly.
    fake_trigger = MagicMock()
    fake_trigger.delay = MagicMock()
    monkeypatch.setattr(s, "trigger_dispatch_task", fake_trigger)

    # Enqueue two files for the same user
    s.enqueue_or_dispatch(
        user_id=7,
        file_id=100,
        file_name="a.txt",
        preview_cache_key="pk1",
        callback_url="",
    )
    s.enqueue_or_dispatch(
        user_id=7,
        file_id=101,
        file_name="b.txt",
        preview_cache_key="pk2",
        callback_url="",
    )

    # First dispatch round
    s.run_dispatch_round()

    # Only one dispatch happens because the queue capacity is 1
    assert apply_async.call_count == 1
    apply_async.assert_called_with(args=[100, "pk1", ""], queue="knowledge_celery")

    # Simulate the dispatched task completing → frees the single slot
    sched = s.FileScheduler(connection=redis_conn)
    sched.complete_file(user_id="7", file_id="100")

    # Second round dispatches the second file into the freed slot
    s.run_dispatch_round()

    assert apply_async.call_count == 2
    apply_async.assert_called_with(args=[101, "pk2", ""], queue="knowledge_celery")


def test_round_robin_across_two_users(redis_conn, monkeypatch):
    monkeypatch.setattr(s, "FileScheduler", _make_scheduler_factory(redis_conn))

    apply_async = MagicMock()
    monkeypatch.setattr(s, "_parse_apply_async", apply_async)
    monkeypatch.setattr(s, "decide_queue", lambda name: "knowledge_celery")
    monkeypatch.setattr(s, "_fair_scheduler_enabled", lambda: True)
    # Capacity 2 → exactly two slots; least-in-flight gives each user one before
    # the cap is hit, so user 1's second file is held back this round.
    monkeypatch.setattr(s, "_fair_scheduler_conf", lambda: _conf(cap=2))
    fake_trigger = MagicMock()
    fake_trigger.delay = MagicMock()
    monkeypatch.setattr(s, "trigger_dispatch_task", fake_trigger)

    # User 1 enqueues 2 files; user 2 enqueues 1
    for fid in (1, 2):
        s.enqueue_or_dispatch(
            user_id=1,
            file_id=fid,
            file_name="x.txt",
            preview_cache_key="",
            callback_url="",
        )
    s.enqueue_or_dispatch(
        user_id=2,
        file_id=99,
        file_name="x.txt",
        preview_cache_key="",
        callback_url="",
    )

    s.run_dispatch_round()

    # Fairness: each user gets one slot before the cap (2) is reached.
    # User 1's first (FIFO) file is 1; user 2's is 99. File 2 is held back.
    assert apply_async.call_count == 2
    dispatched_ids = sorted(call.kwargs["args"][0] for call in apply_async.call_args_list)
    assert dispatched_ids == [1, 99]
