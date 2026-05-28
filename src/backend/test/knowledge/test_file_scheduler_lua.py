import socket

import pytest
import redis

from bisheng.worker.knowledge.scheduler import FileScheduler


def _redis_reachable(host: str = "localhost", port: int = 6379) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _redis_reachable(), reason="Local Redis required for Lua tests")


@pytest.fixture
def redis_conn():
    conn = redis.StrictRedis(host="localhost", port=6379, db=15, decode_responses=True)
    for key in conn.keys("{bisheng_fs}:*"):
        conn.delete(key)
    yield conn
    for key in conn.keys("{bisheng_fs}:*"):
        conn.delete(key)


@pytest.fixture
def scheduler(redis_conn):
    return FileScheduler(connection=redis_conn)


def test_enqueue_pushes_file_and_marks_user_active(scheduler, redis_conn):
    scheduler.enqueue_file(
        user_id="42",
        file_id="100",
        preview_cache_key="pk1",
        callback_url="http://cb",
        file_ext="pdf",
    )
    assert redis_conn.lrange("{bisheng_fs}:queue:42", 0, -1) == ["100"]
    payload = redis_conn.hgetall("{bisheng_fs}:payload:100")
    assert payload["user_id"] == "42"
    assert payload["file_ext"] == "pdf"
    assert payload["preview_cache_key"] == "pk1"
    assert payload["callback_url"] == "http://cb"
    assert redis_conn.sismember("{bisheng_fs}:active_users", "42")
    assert redis_conn.sismember("{bisheng_fs}:inflight_users", "42")
    assert 0 < redis_conn.ttl("{bisheng_fs}:payload:100") <= 14400


def test_dispatch_one_respects_inflight_limit(scheduler, redis_conn):
    for fid in ("1", "2", "3"):
        scheduler.enqueue_file(user_id="9", file_id=fid, preview_cache_key="", callback_url="", file_ext="txt")
    first = scheduler.dispatch_one(user_id="9", limit=1)
    second = scheduler.dispatch_one(user_id="9", limit=1)
    assert first == "1"  # FIFO: earliest enqueued comes out first
    assert second is None  # limit reached
    assert redis_conn.smembers("{bisheng_fs}:inflight:9") == {"1"}


def test_dispatch_one_pops_when_active_users_drained(scheduler, redis_conn):
    scheduler.enqueue_file(user_id="9", file_id="1", preview_cache_key="", callback_url="", file_ext="txt")
    scheduler.dispatch_one(user_id="9", limit=5)
    assert not redis_conn.sismember("{bisheng_fs}:active_users", "9")


def test_rollback_returns_file_to_queue_head(scheduler, redis_conn):
    scheduler.enqueue_file(user_id="9", file_id="1", preview_cache_key="", callback_url="", file_ext="txt")
    scheduler.enqueue_file(user_id="9", file_id="2", preview_cache_key="", callback_url="", file_ext="txt")
    dispatched = scheduler.dispatch_one(user_id="9", limit=5)
    assert dispatched == "1"
    scheduler.rollback_dispatch(user_id="9", file_id="1")
    assert scheduler.dispatch_one(user_id="9", limit=5) == "1"


def test_complete_clears_inflight_and_users_set_when_drained(scheduler, redis_conn):
    scheduler.enqueue_file(user_id="9", file_id="1", preview_cache_key="", callback_url="", file_ext="txt")
    scheduler.dispatch_one(user_id="9", limit=5)
    scheduler.complete_file(user_id="9", file_id="1")
    assert not redis_conn.sismember("{bisheng_fs}:inflight_users", "9")
    assert not redis_conn.smembers("{bisheng_fs}:inflight:9")


def test_complete_is_idempotent(scheduler, redis_conn):
    scheduler.enqueue_file(user_id="9", file_id="1", preview_cache_key="", callback_url="", file_ext="txt")
    scheduler.dispatch_one(user_id="9", limit=5)
    scheduler.complete_file(user_id="9", file_id="1")
    scheduler.complete_file(user_id="9", file_id="1")
    assert not redis_conn.smembers("{bisheng_fs}:inflight:9")
