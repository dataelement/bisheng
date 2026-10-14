"""Independent debug admission never releases a different owner's slot."""

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from bisheng.eplus.infrastructure.debug_gate import RedisDebugGate


async def test_capacity_is_rejected_without_releasing_other_owner():
    redis = AsyncMock()
    redis.set.return_value = False
    with pytest.raises(HTTPException) as exc:
        async with RedisDebugGate(redis).acquire():
            pytest.fail("second execution admitted")
    assert exc.value.status_code == 429
    redis.eval.assert_not_awaited()


async def test_cancellation_releases_only_its_token():
    redis = AsyncMock()
    redis.set.return_value = True
    with pytest.raises(RuntimeError):
        async with RedisDebugGate(redis).acquire():
            raise RuntimeError("stop")
    key, token = redis.set.await_args.args
    assert key == "eplus:debug:active-run"
    assert redis.eval.await_args.args[-2:] == (key, token)
