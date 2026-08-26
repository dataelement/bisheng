from unittest.mock import MagicMock

from bisheng.worker.information.redis_lock import InformationRedisLock


def test_lock_acquire_refresh_and_release_use_token_checks():
    redis = MagicMock()
    redis.set.return_value = True
    redis.eval.side_effect = [1, 1]
    lock = InformationRedisLock(redis, "information:subscription-reconcile", ttl_seconds=30, token="owner")

    assert lock.acquire() is True
    assert lock.refresh() is True
    assert lock.release() is True

    redis.set.assert_called_once_with("information:subscription-reconcile", "owner", nx=True, ex=30)
    assert redis.eval.call_args_list[0].args[2:] == ("information:subscription-reconcile", "owner", 30)
    assert redis.eval.call_args_list[1].args[2:] == ("information:subscription-reconcile", "owner")


def test_lock_does_not_release_another_owner_and_marks_ownership_lost():
    redis = MagicMock()
    redis.set.return_value = True
    redis.eval.side_effect = [0, 0]
    lock = InformationRedisLock(redis, "information:article-sync:A", ttl_seconds=30, token="old")

    assert lock.acquire() is True
    assert lock.refresh() is False
    assert lock.ownership_lost is True
    assert lock.release() is False


def test_redis_failure_never_falls_back_to_an_unlocked_execution():
    redis = MagicMock()
    redis.set.side_effect = RuntimeError("redis unavailable")
    lock = InformationRedisLock(redis, "information:article-sync:A", ttl_seconds=30)

    assert lock.acquire() is False
    assert lock.redis_available is False
    assert lock.acquired is False
