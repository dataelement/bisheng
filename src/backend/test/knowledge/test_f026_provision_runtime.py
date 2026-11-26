import httpx
import pytest

from bisheng.knowledge.application import provider_provision_runtime as runtime


async def test_preset_has_no_default():
    with pytest.raises(ValueError):
        await runtime.load_preset(0, None)


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
        "name": "text-embedding-v3",
        "updated_at": "edited-in-weknora",
        "type": "Embedding",
        "parameters": {"embedding_parameters": {"dimension": 2}},
    }
    async with httpx.AsyncClient(base_url="https://up/api/v1/", transport=httpx.MockTransport(serve)) as client:
        if expected:
            proof = await runtime._probe_model(client, model, "embedding", 4, "42")
            assert proof.dimension == 2 and proof.version == "text-embedding-v3"
        else:
            with pytest.raises(ValueError):
                await runtime._probe_model(client, model, "embedding", 4, "42")
    assert calls == [("POST", "/api/v1/models/embed/debug")]


async def test_model_without_upstream_name_is_not_probed():
    model = {"id": "embed", "tenant_id": 42, "name": " ", "type": "Embedding"}
    async with httpx.AsyncClient(
        base_url="https://up/api/v1/", transport=httpx.MockTransport(lambda r: httpx.Response(500))
    ) as c:
        with pytest.raises(ValueError):
            await runtime._probe_model(c, model, "embedding", 4, "42")


def _instances(monkeypatch, rows):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    async def execute(_):
        return SimpleNamespace(all=lambda: rows)

    @asynccontextmanager
    async def session():
        yield SimpleNamespace(execute=execute)

    monkeypatch.setattr(runtime, "get_async_db_session", session)
    monkeypatch.setattr(runtime, "get_current_tenant_id", lambda: 7)
    monkeypatch.setattr(runtime, "is_tenant_filter_bypassed", lambda: False)


@pytest.mark.parametrize("rows", [[], [(3, "10000", 5), (4, "10001", 1)], [(3, "10000", 0)], [(3, "abc", 5)]])
async def test_creation_needs_exactly_one_ready_instance(monkeypatch, rows):
    _instances(monkeypatch, rows)
    with pytest.raises(ValueError):
        await runtime._instance(7)


async def test_preset_takes_models_chunking_and_extract_from_the_creator(monkeypatch):
    from types import SimpleNamespace

    from bisheng.knowledge.domain.schemas.knowledge_space_schema import (
        ExtractConfigInput,
        ExtractNodeInput,
        ExtractRelationInput,
    )

    async def parameters(p):
        return {}

    _instances(monkeypatch, [(3, "10000", 5)])
    monkeypatch.setattr(runtime, "_parameters", parameters)
    extract = ExtractConfigInput(
        text="demo",
        tags=["t"],
        nodes=[ExtractNodeInput(name="a"), ExtractNodeInput(name="b")],
        relations=[ExtractRelationInput(node1="a", type="rel", node2="b")],
    )
    pick = SimpleNamespace(
        summary_model_id="s",
        embedding_model_id="e",
        vision_model_id="v",
        chunk_size=800,
        overlap=80,
        extract_template_kb_id=None,
        extract_config=extract,
    )
    preset = await runtime.load_preset(7, pick)
    assert preset == runtime.Preset(7, 3, "10000", 5, "s", "e", "v", 800, 80, None, extract.as_weknora())
    with pytest.raises(ValueError):
        await runtime.load_preset(7, SimpleNamespace(**{**vars(pick), "vision_model_id": "s"}))
    with pytest.raises(ValueError):
        await runtime.load_preset(
            7, SimpleNamespace(**{**vars(pick), "extract_template_kb_id": "tpl", "extract_config": extract})
        )


async def test_model_list_keeps_scoped_usable_candidates(monkeypatch):
    from contextlib import asynccontextmanager

    _instances(monkeypatch, [(3, "42", 5)])
    dim = {"embedding_parameters": {"dimension": 1024}}
    rows = [
        {"id": "chat", "tenant_id": 42, "type": "KnowledgeQA", "name": "qwen", "display_name": "千问"},
        {"id": "emb", "tenant_id": 42, "type": "Embedding", "name": "bge", "parameters": dim},
        {"id": "emb-nodim", "tenant_id": 42, "type": "Embedding", "name": "bge", "parameters": {}},
        {"id": "vl", "tenant_id": 42, "type": "VLLM", "name": "qwen-vl"},
        {"id": "other", "tenant_id": 43, "type": "KnowledgeQA", "name": "x"},
        {"id": "rerank", "tenant_id": 42, "type": "Rerank", "name": "r"},
    ]

    @asynccontextmanager
    async def client(_):
        serve = lambda r: httpx.Response(200, json={"success": True, "data": rows})  # noqa: E731
        async with httpx.AsyncClient(base_url="https://up/api/v1/", transport=httpx.MockTransport(serve)) as c:
            yield c

    monkeypatch.setattr(runtime, "_client", client)
    assert await runtime.list_models(7) == {
        "chat": [{"id": "chat", "name": "qwen", "display_name": "千问"}],
        "embedding": [{"id": "emb", "name": "bge", "display_name": "bge", "dimension": 1024}],
        "vision": [{"id": "vl", "name": "qwen-vl", "display_name": "qwen-vl"}],
    }


async def test_extract_templates_keep_enabled_usable_bases(monkeypatch):
    from contextlib import asynccontextmanager

    _instances(monkeypatch, [(3, "42", 5)])
    good = {
        "enabled": True,
        "text": "t",
        "tags": ["x"],
        "nodes": [{"name": "a"}, {"name": "b"}],
        "relations": [{"node1": "a", "type": "rel", "node2": "b"}],
    }
    rows = [
        {"id": "tpl", "name": "Template", "tenant_id": 42, "extract_config": good},
        {"id": "off", "name": "Off", "tenant_id": 42, "extract_config": {**good, "enabled": False}},
        {"id": "other", "name": "Other", "tenant_id": 43, "extract_config": good},
        {"id": "broken", "name": "Broken", "tenant_id": 42, "extract_config": {**good, "relations": []}},
    ]

    @asynccontextmanager
    async def client(_):
        serve = lambda r: httpx.Response(200, json={"success": True, "data": rows})  # noqa: E731
        async with httpx.AsyncClient(base_url="https://up/api/v1/", transport=httpx.MockTransport(serve)) as c:
            yield c

    monkeypatch.setattr(runtime, "_client", client)
    assert await runtime.list_extract_templates(7) == [{"id": "tpl", "name": "Template"}]


@pytest.mark.parametrize(
    "envelope",
    [
        lambda data: {"success": True, "data": data},
        # system/info on current WeKnora builds uses code/msg instead of success.
        lambda data: {"code": 0, "msg": "success", "data": data},
    ],
)
async def test_template_probe_records_current_extract_digest(monkeypatch, envelope):
    extract = {
        "enabled": True,
        "text": "t",
        "tags": ["x"],
        "nodes": [{"name": "a"}, {"name": "b"}],
        "relations": [{"node1": "a", "type": "rel", "node2": "b"}],
    }

    async def models(client, p, uses, rows=None, *, reuse=True):
        return {}

    monkeypatch.setattr(runtime, "_models", models)

    def serve(req):
        if req.url.path.endswith("/system/info"):
            data = {"graph_database_engine": "neo4j"}
        elif req.url.path.endswith("/models"):
            data = []
        else:
            data = {"id": "tpl", "tenant_id": 42, "extract_config": extract}
        return httpx.Response(200, json=envelope(data))

    p = runtime.Preset(7, 3, "42", 1, "s", "e", "v", 512, 32, "tpl", None)
    async with httpx.AsyncClient(base_url="https://up/api/v1/", transport=httpx.MockTransport(serve)) as client:
        proof, copied = await runtime._resolve_extract(client, p)
    assert copied == extract and proof.extract_digest == runtime.digest(extract)


async def test_custom_extract_probe_uses_creator_payload(monkeypatch):
    extract = {
        "enabled": True,
        "text": "custom",
        "tags": ["tag"],
        "nodes": [{"name": "a"}, {"name": "b"}],
        "relations": [{"node1": "a", "type": "owns", "node2": "b"}],
    }

    async def models(client, p, uses, rows=None, *, reuse=True):
        return {}

    monkeypatch.setattr(runtime, "_models", models)

    def serve(req):
        if req.url.path.endswith("/system/info"):
            return httpx.Response(200, json={"code": 0, "msg": "success", "data": {"graph_database_engine": "Neo4j"}})
        assert req.url.path.endswith("/models")
        return httpx.Response(200, json={"success": True, "data": []})

    p = runtime.Preset(7, 3, "42", 1, "s", "e", "v", 512, 32, None, extract)
    async with httpx.AsyncClient(base_url="https://up/api/v1/", transport=httpx.MockTransport(serve)) as client:
        proof, copied = await runtime._resolve_extract(client, p)
    assert copied == extract and proof.sample_text == "custom"


def test_envelope_accepts_code_zero_and_success_true():
    assert runtime._envelope_ok({"success": True, "data": {}})
    assert runtime._envelope_ok({"code": 0, "data": {"graph_database_engine": "Neo4j"}})
    assert not runtime._envelope_ok({"code": 1, "data": {}})
    assert not runtime._envelope_ok({"success": True, "data": None})


@pytest.mark.parametrize(
    "actual,expected,ok",
    [
        ("KnowledgeQA", "KnowledgeQA", True),
        ("chat", "KnowledgeQA", True),
        ("Embedding", "Embedding", True),
        ("embedding", "Embedding", True),
        ("VLLM", "VLLM", True),
        ("vllm", "VLLM", True),
        ("chat", "Embedding", False),
        ("", "KnowledgeQA", False),
    ],
)
def test_model_type_aliases(actual, expected, ok):
    assert runtime._model_type_ok(actual, expected) is ok


async def test_chat_debug_accepts_frontend_model_type_alias():
    model = {
        "id": "chat1",
        "tenant_id": 42,
        "type": "chat",
        "name": "qwen",
        "parameters": {},
    }

    def serve(req):
        assert req.url.path.endswith("/models/chat1/debug")
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "ok": True,
                    "request": {"model_id": "chat1", "model_type": "chat"},
                    "raw_response": {"content": "pong"},
                    "observations": {},
                },
            },
        )

    async with httpx.AsyncClient(base_url="https://up/api/v1/", transport=httpx.MockTransport(serve)) as client:
        proof = await runtime._probe_model(client, model, "chat", 7, "42")
    assert proof.model_id == "chat1" and proof.kind == "chat"


@pytest.mark.parametrize("version", [None, True, 0])
async def test_managed_settings_http_contract(monkeypatch, version):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    p = SimpleNamespace(scope="42", instance_id=7)
    monkeypatch.setattr(runtime, "_target", lambda op: p)
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


@pytest.mark.parametrize(
    "op",
    [
        pytest.param(
            # create_space reconcile carries the requested policy in target_manifest
            __import__("types").SimpleNamespace(
                remote_kb_id="kb", target_manifest=[{"config": {"model_policy": "bisheng-v1"}}]
            ),
            id="create_manifest",
        ),
        pytest.param(
            # settings read uses ActiveTarget — no target_manifest
            __import__("types").SimpleNamespace(
                tenant_id=1,
                provider_instance_id=7,
                remote_scope_id="42",
                remote_kb_id="kb",
                capability_revision=3,
            ),
            id="active_target",
        ),
    ],
)
async def test_read_library_treats_omitted_model_policy_as_managed(monkeypatch, op):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    p = SimpleNamespace(scope="42", instance_id=7, revision=3, tenant_id=1)
    monkeypatch.setattr(runtime, "_target", lambda _op: p)
    proof = SimpleNamespace(dimension=8, version="v1")

    async def models(_client, _preset, uses):
        return {mid: proof for mid, _kind in uses}

    monkeypatch.setattr(runtime, "_models", models)

    def serve(req):
        assert req.url.path.endswith("/knowledge-bases/kb")
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "id": "kb",
                    "tenant_id": 42,
                    "name": "space",
                    "type": "document",
                    # Deployed WeKnora may omit or empty model_policy even when create sent bisheng-v1.
                    "embedding_model_id": "e",
                    "summary_model_id": "s",
                    "vlm_config": {"enabled": True, "model_id": "v"},
                    "chunking_config": {"chunk_size": 512, "chunk_overlap": 64},
                    "indexing_strategy": {
                        "vector_enabled": True,
                        "keyword_enabled": True,
                        "wiki_enabled": True,
                        "graph_enabled": True,
                    },
                    "extract_config": {"enabled": True, "text": "t", "tags": [], "nodes": [], "relations": []},
                    "auto_tag_config": {"enabled": True, "model_id": None},
                    "wiki_config": None,
                },
            },
        )

    @asynccontextmanager
    async def client(_):
        async with httpx.AsyncClient(base_url="https://up/api/v1/", transport=httpx.MockTransport(serve)) as c:
            yield c

    monkeypatch.setattr(runtime, "_client", client)
    observed = await runtime.ProvisionRemote().read_library(op)
    assert observed["config"]["model_policy"] == "bisheng-v1"
