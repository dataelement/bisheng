"""AC-24/AC-31: audit lifecycle is optional and closes before its shared Redis."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from bisheng.dsh.runtime import ModelRuntime


async def test_model_runtime_closes_audit_before_redis_and_handles_absent_audit():
    order = []

    async def audit_close():
        order.append("audit")

    async def redis_close():
        order.append("redis")

    audit = SimpleNamespace(close=AsyncMock(side_effect=audit_close))
    quota = SimpleNamespace(
        topology=SimpleNamespace(close=Mock()), redis=SimpleNamespace(aclose=AsyncMock(side_effect=redis_close))
    )
    runtime = ModelRuntime(None, None, quota, None, audit=audit)
    await runtime.close()
    assert order == ["audit", "redis"]
    audit.close.assert_awaited_once()
    runtime.audit = None
    await runtime.close()
    assert order == ["audit", "redis", "redis"]
