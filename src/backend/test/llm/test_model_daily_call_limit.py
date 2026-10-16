"""Exercise the existing sync/async quota logic without external Redis."""

import ast
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest


@pytest.fixture
def quota():
    path = Path(__file__).parents[2] / "bisheng/llm/domain/utils.py"
    names = {"bisheng_model_limit_check", "sync_bisheng_model_limit_check"}
    nodes = [
        n
        for n in ast.parse(path.read_text()).body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names
    ]
    counts = {}

    def increment(key):
        counts[key] = counts.get(key, 0) + 1
        return counts[key]

    redis = SimpleNamespace(incr=Mock(side_effect=increment), aincr=AsyncMock(side_effect=increment))
    clock = SimpleNamespace(value=datetime(2026, 10, 16), now=lambda: clock.value)
    context = {
        "datetime": clock,
        "get_redis_client": AsyncMock(return_value=redis),
        "get_redis_client_sync": Mock(return_value=redis),
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), context)
    return SimpleNamespace(context=context, clock=clock, counts=counts)


@pytest.mark.parametrize("synchronous", [True, False])
async def test_daily_limit_toggle_exact_threshold_shared_provider_and_new_day(quota, synchronous):
    provider = SimpleNamespace(id=7, name="provider", limit_flag=False, limit=2)
    model = SimpleNamespace(server_info=provider, model_info=SimpleNamespace(model_name="model-a"))

    async def call():
        if synchronous:
            quota.context["sync_bisheng_model_limit_check"](model)
        else:
            await quota.context["bisheng_model_limit_check"](model)

    await call()
    assert quota.counts == {}
    provider.limit_flag = True
    await call()
    model.model_info.model_name = "model-b"
    await call()
    assert quota.counts == {"model_limit:2026-10-16:7": 2}
    with pytest.raises(Exception, match="Quota used up"):
        await call()
    provider.id = 8
    await call()
    assert quota.counts["model_limit:2026-10-16:8"] == 1
    provider.id = 7
    quota.clock.value = datetime(2026, 10, 17)
    await call()
    assert quota.counts["model_limit:2026-10-17:7"] == 1
