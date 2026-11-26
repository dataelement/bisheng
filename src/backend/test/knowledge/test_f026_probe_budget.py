"""Blocking model probes need their own budget and must run together."""

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from bisheng.knowledge.application import provider_provision_runtime as runtime
from bisheng.knowledge.application.provider_v1_runtime import _client_parameters


def test_probe_budget_defaults_and_follows_config(monkeypatch):
    from bisheng.common.services import config_service

    monkeypatch.setattr(config_service, "settings", SimpleNamespace(weknora=None), raising=False)
    assert runtime._probe_timeout().read == 180

    monkeypatch.setattr(
        config_service,
        "settings",
        SimpleNamespace(weknora=SimpleNamespace(probe_timeout_seconds=420)),
        raising=False,
    )
    assert runtime._probe_timeout().read == 420


def test_probe_budget_is_rejected_when_not_a_positive_number(monkeypatch):
    from bisheng.common.services import config_service

    monkeypatch.setattr(
        config_service,
        "settings",
        SimpleNamespace(weknora=SimpleNamespace(probe_timeout_seconds="slow")),
        raising=False,
    )
    assert runtime._probe_timeout().read == 180


def test_explicit_timeout_wins_over_the_transport_default(monkeypatch):
    from bisheng.common.services import config_service

    monkeypatch.setattr(config_service, "settings", SimpleNamespace(weknora=None, weknora_http_endpoint=None))
    monkeypatch.setenv("BS_WEKNORA_PROBE", "fixture-key")
    budget = httpx.Timeout(240, connect=10)
    params = _client_parameters(
        "https://registered.example.invalid",
        "env:BS_WEKNORA_PROBE",
        timeout=budget,
    )
    assert params["timeout"] is budget


async def test_models_probe_concurrently(monkeypatch):
    """Two blocking probes must overlap: the preview pays for the slowest, not the sum."""
    started = 0
    both_started = asyncio.Event()

    async def probe(_client, model, kind, _instance, _scope):
        nonlocal started
        started += 1
        if started == 2:
            both_started.set()
        # Every probe fails unless its peer already started.
        await asyncio.wait_for(both_started.wait(), timeout=1)
        return SimpleNamespace(model_id=model["id"], kind=kind)

    async def data(_client, method, path, **kwargs):
        assert (method, path) == ("GET", "models")
        return [
            {"id": "chat", "tenant_id": 42, "type": "KnowledgeQA"},
            {"id": "vlm", "tenant_id": 42, "type": "VLLM"},
        ]

    monkeypatch.setattr(runtime, "_probe_model", probe)
    monkeypatch.setattr(runtime, "_data", data)

    p = SimpleNamespace(scope="42", instance_id=7)
    proofs = await runtime._models(None, p, [("chat", "chat"), ("vlm", "vision")])
    assert set(proofs) == {"chat", "vlm"}


async def test_models_surfaces_the_first_probe_failure(monkeypatch):
    async def data(_client, method, path, **kwargs):
        return [
            {"id": "chat", "tenant_id": 42, "type": "KnowledgeQA"},
            {"id": "vlm", "tenant_id": 42, "type": "VLLM"},
        ]

    async def probe(_client, model, kind, _instance, _scope):
        await asyncio.sleep(0)
        if model["id"] == "chat":
            raise ValueError("chat unavailable")
        raise ValueError("vlm unavailable")

    monkeypatch.setattr(runtime, "_data", data)
    monkeypatch.setattr(runtime, "_probe_model", probe)

    p = SimpleNamespace(scope="42", instance_id=7)
    with pytest.raises(ValueError, match="chat unavailable"):
        await runtime._models(None, p, [("chat", "chat"), ("vlm", "vision")])


async def test_a_timed_out_call_is_reported_as_an_unavailable_receipt(monkeypatch):
    """A slow probe must not be mistaken for a provider outage in the logs."""

    class Slow:
        timeout = httpx.Timeout(240, connect=10)

        async def request(self, *_args, **_kwargs):
            raise httpx.ReadTimeout("too slow")

    warnings = []
    monkeypatch.setattr(runtime.logger, "warning", lambda message, *a, **k: warnings.append(message.format(*a)))

    with pytest.raises(ConnectionError, match="provider receipt unavailable"):
        await runtime._data(Slow(), "POST", "models/x/debug")
    assert any("timed out" in message for message in warnings)
