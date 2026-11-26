"""Reusing model proofs must never widen what a proof asserts.

A probe is a full remote inference, so an editable creation form reuses a
successful proof for a short TTL instead of re-proving every unchanged model.
These tests pin the reuse boundary: same immutable facts reuse, anything else
re-probes, and an expired or disabled cache trusts nothing.
"""

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from bisheng.knowledge.application import provider_provision_runtime as runtime
from bisheng.knowledge.application.provider_provisioning import ModelProof

PRESET = runtime.Preset(7, 3, "42", 5, "s", "e", "v", 512, 32)


def _model(id_="m1", name="qwen"):
    return {"id": id_, "tenant_id": 42, "type": "KnowledgeQA", "name": name}


def _proof(model_id="m1", version="qwen", kind="chat"):
    return ModelProof(model_id, kind, version, 3, "42", True, None, False)


@pytest.fixture(autouse=True)
def _clean_cache():
    runtime.clear_probe_cache()
    yield
    runtime.clear_probe_cache()


@pytest.fixture
def probes(monkeypatch):
    """Count real probes; the reused path must not reach here twice."""
    calls = []

    async def fake(client, model, kind, instance, scope):
        calls.append((model["id"], kind, instance, scope))
        return _proof(model["id"], model.get("name"), kind)

    monkeypatch.setattr(runtime, "_probe_model", fake)
    monkeypatch.setattr(runtime, "probe_cache_seconds", lambda: 300.0)
    return calls


async def test_an_unchanged_model_is_proved_once(probes):
    async with httpx.AsyncClient(base_url="https://up/api/v1/") as client:
        first = await runtime._probe_reusable(client, _model(), "chat", PRESET)
        second = await runtime._probe_reusable(client, _model(), "chat", PRESET)
    assert probes == [("m1", "chat", 3, "42")]
    assert first == second


async def test_a_different_capability_revision_is_reproved(probes):
    other = runtime.Preset(7, 3, "42", 6, "s", "e", "v", 512, 32)
    async with httpx.AsyncClient(base_url="https://up/api/v1/") as client:
        await runtime._probe_reusable(client, _model(), "chat", PRESET)
        await runtime._probe_reusable(client, _model(), "chat", other)
    assert [call[2:] for call in probes] == [(3, "42"), (3, "42")]
    assert len(probes) == 2


async def test_a_different_model_version_is_reproved(probes):
    async with httpx.AsyncClient(base_url="https://up/api/v1/") as client:
        await runtime._probe_reusable(client, _model(name="qwen"), "chat", PRESET)
        await runtime._probe_reusable(client, _model(name="qwen-next"), "chat", PRESET)
    assert len(probes) == 2


async def test_a_different_kind_or_scope_is_reproved(probes):
    vision = runtime.Preset(7, 3, "99", 5, "s", "e", "v", 512, 32)
    async with httpx.AsyncClient(base_url="https://up/api/v1/") as client:
        await runtime._probe_reusable(client, _model(), "chat", PRESET)
        await runtime._probe_reusable(client, _model(), "vision", PRESET)
        await runtime._probe_reusable(client, _model(), "chat", vision)
    assert len(probes) == 3


async def test_a_disabled_cache_reproves_every_time(probes, monkeypatch):
    monkeypatch.setattr(runtime, "probe_cache_seconds", lambda: 0.0)
    async with httpx.AsyncClient(base_url="https://up/api/v1/") as client:
        await runtime._probe_reusable(client, _model(), "chat", PRESET)
        await runtime._probe_reusable(client, _model(), "chat", PRESET)
    assert len(probes) == 2


async def test_an_expired_proof_is_reproved(probes, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(runtime, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(runtime, "probe_cache_seconds", lambda: 60.0)
    async with httpx.AsyncClient(base_url="https://up/api/v1/") as client:
        await runtime._probe_reusable(client, _model(), "chat", PRESET)
        clock[0] += 59
        await runtime._probe_reusable(client, _model(), "chat", PRESET)
        assert len(probes) == 1
        clock[0] += 2
        await runtime._probe_reusable(client, _model(), "chat", PRESET)
    assert len(probes) == 2


async def test_a_failed_probe_is_never_cached(monkeypatch):
    calls = []

    async def failing(client, model, kind, instance, scope):
        calls.append(kind)
        raise ValueError("provider configuration or evidence unavailable")

    monkeypatch.setattr(runtime, "_probe_model", failing)
    monkeypatch.setattr(runtime, "probe_cache_seconds", lambda: 300.0)
    async with httpx.AsyncClient(base_url="https://up/api/v1/") as client:
        for _ in range(2):
            with pytest.raises(ValueError):
                await runtime._probe_reusable(client, _model(), "chat", PRESET)
    assert calls == ["chat", "chat"]


async def test_cheap_preset_reads_run_once_and_share_the_model_list(monkeypatch):
    """Independent facts are read concurrently; the model list is fetched once."""
    extract = {
        "enabled": True,
        "text": "t",
        "tags": ["x"],
        "nodes": [{"name": "a"}],
        "relations": [{"node1": "a", "type": "rel", "node2": "a"}],
    }
    seen = []

    def serve(request):
        seen.append(request.url.path)
        if request.url.path.endswith("/system/info"):
            return httpx.Response(200, json={"success": True, "data": {"graph_database_engine": "Neo4j"}})
        if request.url.path.endswith("/models"):
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": [
                        {"id": "s", "tenant_id": 42, "type": "KnowledgeQA", "name": "chat-v1"},
                        {
                            "id": "e",
                            "tenant_id": 42,
                            "type": "Embedding",
                            "name": "emb-v1",
                            "parameters": {"embedding_parameters": {"dimension": 2}},
                        },
                        {"id": "v", "tenant_id": 42, "type": "VLLM", "name": "vlm-v1"},
                    ],
                },
            )
        return httpx.Response(
            200, json={"success": True, "data": {"id": "tpl", "tenant_id": 42, "extract_config": extract}}
        )

    async def fake_probe(client, model, kind, instance, scope):
        if kind == "embedding":
            return ModelProof(model["id"], kind, model["name"], instance, scope, True, 2, False)
        return ModelProof(model["id"], kind, model["name"], instance, scope, True, None, kind == "vision")

    monkeypatch.setattr(runtime, "_probe_model", fake_probe)
    monkeypatch.setattr(runtime, "probe_cache_seconds", lambda: 300.0)
    preset = runtime.Preset(7, 3, "42", 5, "s", "e", "v", 512, 32, "tpl", None)
    async with httpx.AsyncClient(base_url="https://up/api/v1/", transport=httpx.MockTransport(serve)) as client:
        proof, copied = await runtime._resolve_extract(client, preset)
    assert copied == extract
    assert proof.extract_digest == runtime.digest(extract)
    assert seen.count("/api/v1/models") == 1
    assert sorted(seen) == ["/api/v1/knowledge-bases/tpl", "/api/v1/models", "/api/v1/system/info"]


async def test_creation_reproves_even_with_a_stored_preview_proof(monkeypatch, shared_store, probes):
    """A cached preview must not stand in for the provider state a create asserts."""
    async with httpx.AsyncClient(base_url="https://up/api/v1/") as client:
        await runtime._probe_reusable(client, _model(), "chat", PRESET)
        assert len(probes) == 1
        await runtime._probe_now(client, _model(), "chat", PRESET)
    assert len(probes) == 2


async def test_concurrent_callers_share_one_inference(monkeypatch):
    """Typing in the form fires several previews; the same facts cost one probe."""
    calls = []

    async def slow(client, model, kind, instance, scope):
        calls.append((model["id"], kind))
        await asyncio.sleep(0.05)
        return _proof(model["id"], model.get("name"), kind)

    monkeypatch.setattr(runtime, "_probe_model", slow)
    async with httpx.AsyncClient(base_url="https://up/api/v1/") as client:
        results = await asyncio.gather(*(runtime._probe_reusable(client, _model(), "chat", PRESET) for _ in range(5)))
    assert len(calls) == 1
    assert all(result == results[0] for result in results)


async def test_a_cancelled_waiter_does_not_break_the_shared_inference(monkeypatch):
    calls = []

    async def slow(client, model, kind, instance, scope):
        calls.append(kind)
        await asyncio.sleep(0.05)
        return _proof(model["id"], model.get("name"), kind)

    monkeypatch.setattr(runtime, "_probe_model", slow)
    async with httpx.AsyncClient(base_url="https://up/api/v1/") as client:
        leader = asyncio.ensure_future(runtime._probe_reusable(client, _model(), "chat", PRESET))
        await asyncio.sleep(0.01)
        waiter = asyncio.ensure_future(runtime._probe_reusable(client, _model(), "chat", PRESET))
        await asyncio.sleep(0.01)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert (await leader).model_id == "m1"
        # A later caller takes the stored proof instead of a new inference.
        assert (await runtime._probe_reusable(client, _model(), "chat", PRESET)).model_id == "m1"
    assert calls == ["chat"]


@pytest.fixture
def shared_store(monkeypatch):
    """Stand-in for the Redis-backed proof cache."""
    rows: dict[str, dict] = {}

    async def shared_get(key):
        return runtime._row_to_proof(rows.get(runtime._shared_probe_key(key)))

    async def shared_put(key, proof, ttl):
        rows[runtime._shared_probe_key(key)] = runtime._proof_to_row(proof)

    monkeypatch.setattr(runtime, "_shared_get", shared_get)
    monkeypatch.setattr(runtime, "_shared_put", shared_put)
    return rows


async def test_a_stored_proof_is_shared_across_processes(shared_store, probes):
    """A restart or a second worker reuses the stored proof instead of re-inferring."""
    async with httpx.AsyncClient(base_url="https://up/api/v1/") as client:
        await runtime._probe_reusable(client, _model(), "chat", PRESET)
        assert len(probes) == 1 and shared_store
        # Simulate a fresh process: the memory map is gone, the shared store is not.
        runtime._probe_cache.clear()
        proof = await runtime._probe_reusable(client, _model(), "chat", PRESET)
    assert proof.model_id == "m1"
    assert len(probes) == 1


async def test_a_row_for_other_facts_does_not_leak(shared_store, probes, monkeypatch):
    async with httpx.AsyncClient(base_url="https://up/api/v1/") as client:
        await runtime._probe_reusable(client, _model(), "chat", PRESET)
        other = runtime.Preset(7, 3, "42", 6, "s", "e", "v", 512, 32)
        await runtime._probe_reusable(client, _model(), "chat", other)
    assert len(probes) == 2


async def test_a_tampered_shared_row_is_not_trusted(monkeypatch, probes):
    """A cache row must still describe a successful proof; anything else re-probes."""

    async def tampered(key):
        return runtime._row_to_proof(
            {"model_id": "m1", "kind": "chat", "version": "qwen", "instance_id": 3, "scope": "42", "available": False}
        )

    async def store(key, proof, ttl):
        return None

    monkeypatch.setattr(runtime, "_shared_get", tampered)
    monkeypatch.setattr(runtime, "_shared_put", store)
    async with httpx.AsyncClient(base_url="https://up/api/v1/") as client:
        proof = await runtime._probe_reusable(client, _model(), "chat", PRESET)
    assert proof.available is True
    assert len(probes) == 1


@pytest.mark.parametrize(
    "row",
    [
        None,
        {},
        {"model_id": "", "kind": "chat", "version": "v", "instance_id": 3, "scope": "42", "available": True},
        {"model_id": "m1", "kind": "chat", "version": "", "instance_id": 3, "scope": "42", "available": True},
        {"model_id": "m1", "kind": "audio", "version": "v", "instance_id": 3, "scope": "42", "available": True},
        {"model_id": "m1", "kind": "embedding", "version": "v", "instance_id": 3, "scope": "42", "available": True},
        {"model_id": "m1", "kind": "vision", "version": "v", "instance_id": 3, "scope": "42", "available": True},
    ],
)
def test_cached_rows_must_assert_a_complete_proof(row):
    assert runtime._row_to_proof(row) is None


def _debug_serve(*, reject_options: bool):
    """MockTransport that only answers `ok` when the caller omits options."""
    seen = []

    def serve(request):
        import json as _json
        from urllib.parse import parse_qs

        body = parse_qs(request.content.decode())
        seen.append(body)
        has_options = "options" in body
        if reject_options and has_options:
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {"ok": False, "request": {"model_id": "m1", "model_type": "chat"}, "error": "unsupported option"},
                },
            )
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "ok": True,
                    "request": {"model_id": "m1", "model_type": "chat"},
                    "raw_response": {"content": "pong"},
                    "observations": {},
                },
            },
        )

    return serve, seen


@pytest.mark.parametrize("reject_options,expected_calls", [(False, 1), (True, 2)])
async def test_a_reasoning_model_is_probed_with_capped_generation(reject_options, expected_calls):
    """Capping the answer is what turns a 60s probe into a couple of seconds.

    A vendor that rejects the options is probed again without them rather than
    failing a model that actually answers.
    """
    serve, seen = _debug_serve(reject_options=reject_options)
    model = _model()
    async with httpx.AsyncClient(base_url="https://up/api/v1/", transport=httpx.MockTransport(serve)) as client:
        proof = await runtime._probe_model(client, model, "chat", 7, "42")
    assert proof.model_id == "m1"
    assert len(seen) == expected_calls
    assert "options" in seen[0]
    assert '"max_tokens"' in seen[0]["options"][0]
    if reject_options:
        assert "options" not in seen[1]


async def test_an_embedding_probe_sends_no_generation_options():
    calls = []

    def serve(request):
        from urllib.parse import parse_qs

        body = parse_qs(request.content.decode())
        calls.append(body)
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "ok": True,
                    "request": {"model_id": "emb", "model_type": "Embedding"},
                    "raw_response": [0.5, 0.5],
                    "observations": {"dimension": 2},
                },
            },
        )

    model = {
        "id": "emb", "tenant_id": 42, "name": "text-embedding-v3", "type": "Embedding",
        "parameters": {"embedding_parameters": {"dimension": 2}},
    }
    async with httpx.AsyncClient(base_url="https://up/api/v1/", transport=httpx.MockTransport(serve)) as client:
        await runtime._probe_model(client, model, "embedding", 7, "42")
    assert calls and all("options" not in body for body in calls)
