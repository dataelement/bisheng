import httpx
import pytest

from bisheng.knowledge.application import provider_provision_runtime as runtime


async def test_preset_has_no_default(monkeypatch):
    monkeypatch.delenv("BS_WEKNORA_PRESET_7", raising=False)
    with pytest.raises(ValueError):
        await runtime.load_preset(7)


@pytest.mark.parametrize(
    "ok,vector,dim,expected",
    [
        (True, [0.5, 0.5], 2, True),
        (False, [0.5, 0.5], 2, False),
        (True, [], 2, False),
        (True, [True, False], 2, False),
        (True, [0.2], 2, False),
    ],
)
async def test_embedding_requires_actual_scoped_model_output(ok, vector, dim, expected):
    calls = []

    def serve(req):
        calls.append((req.method, req.url.path))
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "ok": ok,
                    "raw_response": vector,
                    "request": {"model_id": "embed", "model_type": "Embedding"},
                    "observations": {"dimension": dim},
                },
            },
        )

    model = {
        "id": "embed",
        "tenant_id": 42,
        "updated_at": "r1",
        "type": "Embedding",
        "parameters": {"embedding_parameters": {"dimension": 2}},
    }
    async with httpx.AsyncClient(base_url="https://up/api/v1/", transport=httpx.MockTransport(serve)) as client:
        if expected:
            proof = await runtime._probe_model(
                client, model, "embedding", 4, "42", {"updated_at": "r1", "version": "immutable"}
            )
            assert proof.dimension == 2 and proof.version == "immutable"
        else:
            with pytest.raises(ValueError):
                await runtime._probe_model(
                    client, model, "embedding", 4, "42", {"updated_at": "r1", "version": "immutable"}
                )
    assert calls == [("POST", "/api/v1/models/embed/debug")]


@pytest.mark.parametrize("version", [None, True, 0])
async def test_managed_settings_http_contract(monkeypatch, version):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    p = SimpleNamespace(scope="42", instance_id=7)
    monkeypatch.setattr(runtime, "_target", lambda op: (p, {}))
    calls = []
    patch = {"wiki_model_id": None}

    def serve(req):
        import json

        calls.append(req.url.path)
        if req.url.path.endswith("/managed-settings"):
            assert req.method == "PUT" and json.loads(req.content) == {
                "operation_id": "op",
                "digest": runtime.digest(patch),
                "patch": patch,
                "expected_version": 0,
            }
            data = {}
        elif req.url.path.endswith("/models"):
            data = []
        else:
            data = {"tenant_id": 42, "id": "kb", "model_policy": "bisheng-v1", "settings_version": version}
        return httpx.Response(200, json={"success": True, "data": data})

    @asynccontextmanager
    async def client(_):
        async with httpx.AsyncClient(base_url="https://up/api/v1/", transport=httpx.MockTransport(serve)) as c:
            yield c

    monkeypatch.setattr(runtime, "_client", client)
    op = SimpleNamespace(remote_kb_id="kb", operation_id="op", target_manifest=[{"expected_remote_version": 0}])
    remote = runtime.ProvisionRemote()
    if type(version) is not int:
        with pytest.raises(ValueError):
            await remote.probe_settings(op, patch)
        assert len(calls) == 1
    else:
        assert await remote.probe_settings(op, patch) == ({}, 0)
        await remote.patch_library(op, patch)
        assert calls[-1] == "/api/v1/knowledge-bases/kb/managed-settings"
