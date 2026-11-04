"""F087: which context window a task-mode model runs with, and how much of it is input.

Covers the source priority (advanced config > Ollama num_ctx > provider API > unknown)
and the three usable-input rules from spec.md's glossary.
"""

import pytest

from bisheng.llm.domain.services.context_window import (
    ContextWindowService,
    ModelSnapshot,
)
from bisheng.llm.domain.services.context_window_probes import ProbeResult


class _NoCache:
    async def aget(self, key):
        return None

    async def aset(self, key, value, expiration=3600):
        return True

    async def adelete(self, key):
        return 0


def _snapshot(server_type="vllm", model_config=None, client_params=None, model_id=7) -> ModelSnapshot:
    return ModelSnapshot(
        model_id=model_id,
        model_name="qwen3-32b",
        server_type=server_type,
        model_config=model_config or {},
        client_params=client_params if client_params is not None else {"base_url": "http://vllm.local/v1"},
    )


@pytest.fixture
def probe_calls(monkeypatch):
    calls = []

    async def fake_probe(snapshot):
        calls.append(snapshot.model_id)
        return ProbeResult(window=133120, kind="total", source="deployed")

    monkeypatch.setattr("bisheng.llm.domain.services.context_window.probe_context_window", fake_probe)
    return calls


async def test_advanced_config_wins_over_provider(probe_calls):
    result = await ContextWindowService.resolve_snapshot(
        _snapshot(model_config={"user_kwargs": '{"context_window": 32768}'}), cache=_NoCache()
    )

    assert (result.window, result.usable_input, result.source) == (32768, 32768, "manual")
    assert probe_calls == []


async def test_advanced_config_given_as_dict(probe_calls):
    result = await ContextWindowService.resolve_snapshot(
        _snapshot(model_config={"user_kwargs": {"context_window": 65536}}), cache=_NoCache()
    )

    assert result.source == "manual"
    assert result.window == 65536


@pytest.mark.parametrize("bad", ["abc", 0, -5, 1.5, True])
async def test_invalid_manual_value_is_ignored(probe_calls, bad):
    result = await ContextWindowService.resolve_snapshot(
        _snapshot(model_config={"user_kwargs": {"context_window": bad}}), cache=_NoCache()
    )

    # Falls through to the provider API.
    assert result.source == "deployed"
    assert probe_calls == [7]


async def test_malformed_advanced_config_falls_through(probe_calls):
    result = await ContextWindowService.resolve_snapshot(
        _snapshot(model_config={"user_kwargs": "{not json"}), cache=_NoCache()
    )

    assert result.source == "deployed"


async def test_ollama_num_ctx_is_the_window_and_not_subtracted(probe_calls):
    result = await ContextWindowService.resolve_snapshot(
        _snapshot(server_type="ollama", client_params={"base_url": "http://ollama:11434", "num_ctx": 32768}),
        cache=_NoCache(),
    )

    assert (result.window, result.usable_input, result.source) == (32768, 32768, "ollama_num_ctx")
    assert probe_calls == []


async def test_max_tokens_is_subtracted_from_a_total_window(probe_calls):
    result = await ContextWindowService.resolve_snapshot(
        _snapshot(client_params={"base_url": "http://vllm.local/v1", "max_tokens": 8192}), cache=_NoCache()
    )

    assert result.usable_input == 133120 - 8192


async def test_input_only_limit_is_not_reduced_again(monkeypatch):
    async def fake_probe(snapshot):
        return ProbeResult(window=200000, kind="input", source="published")

    monkeypatch.setattr("bisheng.llm.domain.services.context_window.probe_context_window", fake_probe)
    result = await ContextWindowService.resolve_snapshot(
        _snapshot(server_type="anthropic", client_params={"max_tokens": 8192}), cache=_NoCache()
    )

    assert (result.usable_input, result.kind) == (200000, "input")


async def test_max_tokens_not_below_window_means_unknown(probe_calls):
    result = await ContextWindowService.resolve_snapshot(
        _snapshot(
            model_config={"user_kwargs": {"context_window": 8192}},
            client_params={"base_url": "http://vllm.local/v1", "max_tokens": 8192},
        ),
        cache=_NoCache(),
    )

    assert result.usable_input is None
    assert result.source == "unknown"


async def test_no_probe_for_the_server_type_means_unknown(monkeypatch):
    async def fake_probe(snapshot):
        return None

    monkeypatch.setattr("bisheng.llm.domain.services.context_window.probe_context_window", fake_probe)
    result = await ContextWindowService.resolve_snapshot(_snapshot(server_type="zhipu"), cache=_NoCache())

    assert (result.window, result.usable_input, result.source) == (None, None, "unknown")
