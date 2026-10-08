"""Model runtime activates Redis without MinIO and reports storage failures honestly."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.dsh import DshQuotaUnavailableError
from bisheng.dsh.runtime import ModelRuntime
from test.dsh.test_model_service import principal


async def test_runtime_uses_redis_and_can_retry_after_a_connection_failure():
    topology = SimpleNamespace(activate=AsyncMock(side_effect=[ConnectionError("offline"), None]))
    runtime = ModelRuntime(None, None, SimpleNamespace(topology=topology), object())
    with pytest.raises(ConnectionError):
        await runtime.activate()
    await runtime.activate()
    assert topology.activate.await_count == 2


async def test_runtime_reads_automatically_recovered_usage_and_does_not_invent_zero():
    topology = SimpleNamespace(activate=AsyncMock())
    usage = SimpleNamespace(read_usage=AsyncMock(return_value={"used": 123}))
    runtime = ModelRuntime(None, usage, SimpleNamespace(topology=topology), object())
    assert await runtime.prepare_month(principal(), "2026-09") == {"used": 123}
    usage.read_usage.side_effect = RuntimeError("SQL unavailable")
    with pytest.raises(DshQuotaUnavailableError):
        await runtime.prepare_month(principal(), "2026-09")
