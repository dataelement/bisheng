import socket
from urllib.parse import urlparse

import pytest
import redis

from bisheng.common.services.config_service import settings
from bisheng.worker.knowledge.scheduler import FileScheduler

# Run the Lua scripts against the Redis configured in config.yaml, isolated on a
# dedicated db so we never touch real application data.
_parsed = urlparse(settings.redis_url)
REDIS_HOST = _parsed.hostname or "localhost"
REDIS_PORT = _parsed.port or 6379
REDIS_TEST_DB = 15


def _redis_reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _redis_reachable(REDIS_HOST, REDIS_PORT),
    reason="Configured Redis required for Lua tests",
)


@pytest.fixture
def redis_conn():
    conn = redis.StrictRedis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_TEST_DB, decode_responses=True)
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
    assert 0 < redis_conn.ttl("{bisheng_fs}:payload:100") <= 604800


def test_dispatch_one_pops_fifo_without_per_user_limit(scheduler, redis_conn):
    """No per-user in-flight ceiling: successive pops drain the queue in FIFO order."""
    for fid in ("1", "2", "3"):
        scheduler.enqueue_file(user_id="9", file_id=fid, preview_cache_key="", callback_url="", file_ext="txt")
    first = scheduler.dispatch_one(user_id="9")
    second = scheduler.dispatch_one(user_id="9")
    assert first == "1"  # FIFO: earliest enqueued comes out first
    assert second == "2"  # NOT blocked by any per-user limit
    assert redis_conn.smembers("{bisheng_fs}:inflight:9") == {"1", "2"}
    assert scheduler.inflight_count(user_id="9") == 2


def test_dispatch_one_returns_none_when_queue_empty(scheduler, redis_conn):
    scheduler.enqueue_file(user_id="9", file_id="1", preview_cache_key="", callback_url="", file_ext="txt")
    scheduler.dispatch_one(user_id="9")
    assert scheduler.dispatch_one(user_id="9") is None
    assert not redis_conn.sismember("{bisheng_fs}:active_users", "9")


def test_confirm_dispatch_increments_queue_counter_and_drops_payload(scheduler, redis_conn):
    scheduler.enqueue_file(user_id="9", file_id="1", preview_cache_key="pk", callback_url="cb", file_ext="txt")
    scheduler.dispatch_one(user_id="9")
    scheduler.confirm_dispatch(file_id="1", queue="knowledge_celery")

    assert scheduler.inflight_total(queue="knowledge_celery") == 1
    assert redis_conn.hget("{bisheng_fs}:inflight_queue", "1") == "knowledge_celery"
    # payload consumed
    assert redis_conn.hgetall("{bisheng_fs}:payload:1") == {}


def test_complete_returns_slot_to_queue_counter(scheduler, redis_conn):
    scheduler.enqueue_file(user_id="9", file_id="1", preview_cache_key="", callback_url="", file_ext="txt")
    scheduler.dispatch_one(user_id="9")
    scheduler.confirm_dispatch(file_id="1", queue="ocr_celery")
    assert scheduler.inflight_total(queue="ocr_celery") == 1

    scheduler.complete_file(user_id="9", file_id="1")
    assert scheduler.inflight_total(queue="ocr_celery") == 0
    assert redis_conn.hget("{bisheng_fs}:inflight_queue", "1") is None
    assert not redis_conn.sismember("{bisheng_fs}:inflight_users", "9")
    assert not redis_conn.smembers("{bisheng_fs}:inflight:9")


def test_complete_is_idempotent(scheduler, redis_conn):
    scheduler.enqueue_file(user_id="9", file_id="1", preview_cache_key="", callback_url="", file_ext="txt")
    scheduler.dispatch_one(user_id="9")
    scheduler.confirm_dispatch(file_id="1", queue="knowledge_celery")
    scheduler.complete_file(user_id="9", file_id="1")
    scheduler.complete_file(user_id="9", file_id="1")
    assert not redis_conn.smembers("{bisheng_fs}:inflight:9")
    # counter must not go negative on a second complete (HDEL already removed the map entry)
    assert scheduler.inflight_total(queue="knowledge_celery") == 0


def test_rollback_returns_file_to_queue_head_and_no_counter_change(scheduler, redis_conn):
    scheduler.enqueue_file(user_id="9", file_id="1", preview_cache_key="", callback_url="", file_ext="txt")
    scheduler.enqueue_file(user_id="9", file_id="2", preview_cache_key="", callback_url="", file_ext="txt")
    dispatched = scheduler.dispatch_one(user_id="9")
    assert dispatched == "1"
    # rollback happens before confirm, so the queue counter was never bumped
    scheduler.rollback_dispatch(user_id="9", file_id="1")
    assert scheduler.dispatch_one(user_id="9") == "1"
    assert scheduler.inflight_total(queue="knowledge_celery") == 0


def test_recompute_inflight_totals_heals_drift(scheduler, redis_conn):
    scheduler.enqueue_file(user_id="9", file_id="1", preview_cache_key="", callback_url="", file_ext="txt")
    scheduler.dispatch_one(user_id="9")
    scheduler.confirm_dispatch(file_id="1", queue="knowledge_celery")
    # Corrupt the counter to simulate a lost callback.
    redis_conn.set("{bisheng_fs}:inflight_total:knowledge_celery", 99)
    redis_conn.set("{bisheng_fs}:inflight_total:ocr_celery", 7)

    scheduler.recompute_inflight_totals(queues=["knowledge_celery", "ocr_celery"])

    assert scheduler.inflight_total(queue="knowledge_celery") == 1  # one mapped file
    assert scheduler.inflight_total(queue="ocr_celery") == 0  # reset, no mapped files


def test_purge_file_releases_confirmed_slot(scheduler, redis_conn):
    scheduler.enqueue_file(user_id="9", file_id="1", preview_cache_key="", callback_url="", file_ext="txt")
    scheduler.dispatch_one(user_id="9")
    scheduler.confirm_dispatch(file_id="1", queue="knowledge_celery")
    assert scheduler.inflight_total(queue="knowledge_celery") == 1

    scheduler.purge_file(user_id="9", file_id="1")
    assert scheduler.inflight_total(queue="knowledge_celery") == 0
    assert redis_conn.hget("{bisheng_fs}:inflight_queue", "1") is None
    assert not redis_conn.smembers("{bisheng_fs}:inflight:9")


def test_acquire_dispatch_lock_returns_token_only_first_caller(scheduler, redis_conn):
    token = scheduler.acquire_dispatch_lock(ttl_seconds=10)
    assert token is not None
    assert isinstance(token, str)
    assert scheduler.acquire_dispatch_lock(ttl_seconds=10) is None
    stored = redis_conn.get("{bisheng_fs}:dispatch_lock")
    assert stored == token


def test_release_dispatch_lock_only_releases_own_token(scheduler, redis_conn):
    token_a = scheduler.acquire_dispatch_lock(ttl_seconds=10)
    assert token_a is not None
    scheduler.release_dispatch_lock("not_the_right_token")
    assert redis_conn.get("{bisheng_fs}:dispatch_lock") == token_a
    scheduler.release_dispatch_lock(token_a)
    assert redis_conn.get("{bisheng_fs}:dispatch_lock") is None
    token_b = scheduler.acquire_dispatch_lock(ttl_seconds=10)
    assert token_b is not None
    assert token_b != token_a


def test_drop_inflight_discards_without_requeue_or_counter_change(scheduler, redis_conn):
    """A ghost in-flight entry (payload lost, never confirmed) must be removed
    from inflight WITHOUT being pushed back to the queue and WITHOUT touching the
    queue counter — otherwise it becomes a poison pill that blocks the queue."""
    scheduler.enqueue_file(user_id="9", file_id="1", preview_cache_key="", callback_url="", file_ext="txt")
    scheduler.enqueue_file(user_id="9", file_id="2", preview_cache_key="", callback_url="", file_ext="txt")
    dispatched = scheduler.dispatch_one(user_id="9")  # RPOP tail → "1"
    assert dispatched == "1"

    scheduler.drop_inflight(user_id="9", file_id="1")

    # not re-queued, payload gone, inflight cleared, counter untouched
    assert redis_conn.lrange("{bisheng_fs}:queue:9", 0, -1) == ["2"]
    assert redis_conn.hgetall("{bisheng_fs}:payload:1") == {}
    assert "1" not in redis_conn.smembers("{bisheng_fs}:inflight:9")
    assert scheduler.inflight_total(queue="knowledge_celery") == 0


def test_drop_inflight_clears_inflight_users_when_empty(scheduler, redis_conn):
    scheduler.enqueue_file(user_id="9", file_id="1", preview_cache_key="", callback_url="", file_ext="txt")
    scheduler.dispatch_one(user_id="9")
    scheduler.drop_inflight(user_id="9", file_id="1")
    assert not redis_conn.sismember("{bisheng_fs}:inflight_users", "9")


def test_put_payload_writes_hash_with_ttl(scheduler, redis_conn):
    scheduler.put_payload(
        file_id="5",
        preview_cache_key="",
        callback_url="",
        user_id="9",
        file_ext="pdf",
        tenant_id="3",
        ttl_seconds=120,
    )
    payload = redis_conn.hgetall("{bisheng_fs}:payload:5")
    assert payload == {
        "preview_cache_key": "",
        "callback_url": "",
        "user_id": "9",
        "file_ext": "pdf",
        "tenant_id": "3",
    }
    assert 0 < redis_conn.ttl("{bisheng_fs}:payload:5") <= 120


def test_queued_files_returns_queue_contents(scheduler, redis_conn):
    for fid in ("1", "2", "3"):
        scheduler.enqueue_file(user_id="9", file_id=fid, preview_cache_key="", callback_url="", file_ext="txt")
    # LPUSH order → newest first; queued_files mirrors LRANGE 0 -1
    assert scheduler.queued_files(user_id="9") == ["3", "2", "1"]


def test_remove_from_queue_removes_all_occurrences(scheduler, redis_conn):
    scheduler.enqueue_file(user_id="9", file_id="1", preview_cache_key="", callback_url="", file_ext="txt")
    redis_conn.rpush("{bisheng_fs}:queue:9", "1")  # simulate an accidental duplicate
    scheduler.remove_from_queue(user_id="9", file_id="1")
    assert redis_conn.lrange("{bisheng_fs}:queue:9", 0, -1) == []


def test_dispatch_re_adds_user_to_inflight_users(scheduler, redis_conn):
    scheduler.enqueue_file(user_id="9", file_id="1", preview_cache_key="", callback_url="", file_ext="txt")
    scheduler.enqueue_file(user_id="9", file_id="2", preview_cache_key="", callback_url="", file_ext="txt")
    scheduler.dispatch_one(user_id="9")
    scheduler.complete_file(user_id="9", file_id="1")
    assert not redis_conn.sismember("{bisheng_fs}:inflight_users", "9")
    scheduler.dispatch_one(user_id="9")
    assert redis_conn.sismember("{bisheng_fs}:inflight_users", "9")
