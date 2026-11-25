"""Direct cache producers preserve authenticated contracts and exact-byte CAS."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.core.cache.serialization import RedisSerializationError, decode_redis_value, encode_redis_value


@pytest.mark.parametrize("race", [False, True])
async def test_mobile_cas_uses_observed_ciphertext_and_preserves_winner(monkeypatch, race):
    from bisheng.core.cache import redis_manager
    from bisheng.dsh.domain.services.mobile_session import RedisCurrentSession
    from bisheng.user.domain.const import USER_CURRENT_SESSION

    key = USER_CURRENT_SESSION.format(17)
    observed = encode_redis_value(key, "before")
    state = [observed, 40]

    async def evaluate(script, count, actual_key, mode, expected, candidate, ttl):
        assert expected == observed and actual_key == key and mode == "present"
        assert decode_redis_value(key, candidate) == "after"
        if race:
            state[0] = encode_redis_value(key, "winner")
        if state[0] != expected:
            return 0
        state[:] = [candidate, ttl]
        return 1

    rc = SimpleNamespace(get=AsyncMock(return_value=observed), eval=AsyncMock(side_effect=evaluate))
    monkeypatch.setattr(
        redis_manager,
        "get_redis_client",
        AsyncMock(return_value=SimpleNamespace(acluster_nodes=AsyncMock(), async_connection=rc)),
    )
    assert await RedisCurrentSession().replace(17, "before", "after", 60) is not race
    assert decode_redis_value(key, state[0]) == ("winner" if race else "after")
    assert state[1] == (40 if race else 60)


async def test_mobile_invalid_auth_never_reaches_lua(monkeypatch):
    from bisheng.core.cache import redis_manager
    from bisheng.dsh.domain.services.mobile_session import RedisCurrentSession

    rc = SimpleNamespace(get=AsyncMock(return_value=b"raw unauthenticated"), eval=AsyncMock())
    monkeypatch.setattr(
        redis_manager,
        "get_redis_client",
        AsyncMock(return_value=SimpleNamespace(acluster_nodes=AsyncMock(), async_connection=rc)),
    )
    with pytest.raises(RedisSerializationError):
        await RedisCurrentSession().replace(17, "before", "after", 60)
    rc.eval.assert_not_called()


async def test_state_pipeline_writer_authenticates_each_actual_key(monkeypatch):
    from bisheng.linsight.domain.services.state_message_manager import LinsightStateMessageManager

    class Pipe:
        set = AsyncMock()
        sadd = AsyncMock()
        expire = AsyncMock()
        execute = AsyncMock()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    pipe = Pipe()
    mgr = LinsightStateMessageManager.__new__(LinsightStateMessageManager)
    mgr._keys = {"execution_tasks": "session:tasks:", "task_ids": "session:ids"}
    mgr._redis_client = SimpleNamespace(async_pipeline=lambda **kw: pipe)
    tasks = [{"id": "a"}, {"id": "b"}]
    await mgr._cache_execution_tasks(tasks)
    assert len(pipe.set.call_args_list) == 2
    for task, call in zip(tasks, pipe.set.call_args_list, strict=True):
        key, raw = call.args
        assert key == "session:tasks:" + task["id"]
        assert decode_redis_value(key, raw) == task
