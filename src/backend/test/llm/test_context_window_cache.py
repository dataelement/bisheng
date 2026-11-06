"""F087: provider-API results are cached in Redis and dropped when the model is saved."""

import pytest

from bisheng.llm.domain.services.context_window import ContextWindowService, ModelSnapshot
from bisheng.llm.domain.services.context_window_probes import ProbeResult


class _FakeRedis:
    def __init__(self):
        self.store: dict = {}
        self.ttl: dict = {}

    async def aget(self, key):
        return self.store.get(key)

    async def aset(self, key, value, expiration=3600):
        self.store[key] = value
        self.ttl[key] = expiration
        return True

    async def adelete(self, key):
        return 1 if self.store.pop(key, None) is not None else 0


class _BrokenRedis:
    async def aget(self, key):
        raise ConnectionError("redis down")

    async def aset(self, key, value, expiration=3600):
        raise ConnectionError("redis down")

    async def adelete(self, key):
        raise ConnectionError("redis down")


def _snapshot(model_id=7) -> ModelSnapshot:
    return ModelSnapshot(
        model_id=model_id,
        model_name="qwen3-32b",
        server_type="vllm",
        model_config={},
        client_params={"base_url": "http://vllm.local/v1"},
    )


@pytest.fixture
def probe(monkeypatch):
    state = {"calls": 0, "result": ProbeResult(window=133120, kind="total", source="deployed")}

    async def fake_probe(snapshot):
        state["calls"] += 1
        return state["result"]

    monkeypatch.setattr("bisheng.llm.domain.services.context_window.probe_context_window", fake_probe)
    return state


async def test_success_is_cached_for_an_hour(probe):
    redis = _FakeRedis()

    first = await ContextWindowService.resolve_snapshot(_snapshot(), cache=redis)
    second = await ContextWindowService.resolve_snapshot(_snapshot(), cache=redis)

    assert first == second
    assert probe["calls"] == 1
    assert list(redis.ttl.values()) == [3600]


async def test_failure_is_cached_for_five_minutes(probe):
    probe["result"] = None
    redis = _FakeRedis()

    first = await ContextWindowService.resolve_snapshot(_snapshot(), cache=redis)
    second = await ContextWindowService.resolve_snapshot(_snapshot(), cache=redis)

    assert first.source == second.source == "unknown"
    assert probe["calls"] == 1
    assert list(redis.ttl.values()) == [300]


async def test_invalidate_forces_a_fresh_read(probe):
    redis = _FakeRedis()
    await ContextWindowService.resolve_snapshot(_snapshot(), cache=redis)

    await ContextWindowService.invalidate([7], cache=redis)
    probe["result"] = ProbeResult(window=32768, kind="total", source="deployed")
    result = await ContextWindowService.resolve_snapshot(_snapshot(), cache=redis)

    assert result.window == 32768
    assert probe["calls"] == 2


async def test_redis_failure_never_breaks_resolve(probe):
    result = await ContextWindowService.resolve_snapshot(_snapshot(), cache=_BrokenRedis())

    # The probe still answers; only caching is lost.
    assert result.window == 133120


async def test_redis_failure_never_breaks_invalidate():
    await ContextWindowService.invalidate([7], cache=_BrokenRedis())


def test_saving_or_verifying_a_model_drops_its_cached_window():
    """update_llm_server / verify_model_status must invalidate; going online/offline must not.

    Checked at source level: driving these service methods needs the database, and
    the contract is only "the call is there, next to the in-process cache eviction".
    """
    import inspect

    from bisheng.llm.domain.services.llm import LLMService

    assert "ContextWindowService.invalidate" in inspect.getsource(LLMService.update_llm_server)
    assert "ContextWindowService.invalidate" in inspect.getsource(LLMService.verify_model_status)
    assert "ContextWindowService.invalidate" not in inspect.getsource(LLMService.update_model_online)


async def test_value_read_against_an_older_config_is_a_miss(probe):
    """A worker still on the pre-save config may write the old answer back after the save."""
    redis = _FakeRedis()
    old = _snapshot()
    await ContextWindowService.resolve_snapshot(old, cache=redis)

    moved = ModelSnapshot(
        model_id=7,
        model_name="qwen3-32b",
        server_type="vllm",
        model_config={},
        client_params={"base_url": "http://new-vllm.local/v1"},
    )
    probe["result"] = ProbeResult(window=65536, kind="total", source="deployed")
    result = await ContextWindowService.resolve_snapshot(moved, cache=redis)

    assert result.window == 65536
    assert probe["calls"] == 2


def test_snapshot_repr_hides_credentials():
    snapshot = ModelSnapshot(
        model_id=7,
        model_name="m",
        server_type="vllm",
        model_config={"user_kwargs": {"api_key": "sk-secret"}},
        client_params={"api_key": "sk-secret"},
    )
    assert "sk-secret" not in repr(snapshot)
