"""Real index and model-call adapters, wired with stubbed clients (AC-45, AC-58)."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.common.errcode.memory import MemoryNoModelError
from bisheng.memory.domain.ports import VectorUnconfigured, build_scope_filter
from bisheng.memory.domain.services import index as index_mod
from bisheng.memory.domain.services import llm as llm_mod
from bisheng.memory.domain.services.index import ES_INDEX_NAME, PlatformMemoryIndex, milvus_collection_name


class StubES:
    def __init__(self):
        self.added, self.deleted, self.searches = [], [], []

    async def aadd_texts(self, texts, metadatas=None, ids=None, **kw):
        self.added.append((texts, metadatas, ids))
        return ids

    async def adelete(self, ids=None, **kw):
        self.deleted.append(ids)

    async def asimilarity_search_with_score(self, query, k=4, filter=None, **kw):
        self.searches.append((query, k, filter))
        doc = SimpleNamespace(metadata={"item_id": "i1"})
        return [(doc, 3.0)]


class StubMilvus:
    def __init__(self):
        self.added, self.deleted, self.searches = [], [], []

    def add_embeddings(self, texts, embeddings, metadatas=None, **kw):
        self.added.append((texts, embeddings, metadatas))

    def delete(self, ids=None, expr=None, **kw):
        self.deleted.append(expr)

    def similarity_search_with_score_by_vector(self, embedding, k=4, expr=None, **kw):
        self.searches.append((embedding, k, expr))
        return [(SimpleNamespace(metadata={"item_id": "i2"}), 0.1)]


class StubEmbeddings:
    def __init__(self, delay=0.0):
        self.delay = delay

    async def aembed_query(self, text):
        await asyncio.sleep(self.delay)
        return [0.1, 0.2]

    async def aembed_documents(self, texts):
        await asyncio.sleep(self.delay)
        return [[0.1, 0.2] for _ in texts]


@pytest.fixture
def stubs(monkeypatch):
    es, milvus = StubES(), StubMilvus()
    names = {}

    def _milvus(name, embedding):
        names["milvus"] = name
        return milvus

    async def _loader(ctx):
        return "7", StubEmbeddings()

    idx = PlatformMemoryIndex(es_factory=lambda: es, milvus_factory=_milvus, embedding_loader=_loader)
    return SimpleNamespace(es=es, milvus=milvus, names=names, index=idx)


def test_names():
    assert ES_INDEX_NAME == "bisheng_memory_item"
    assert milvus_collection_name("7") == "bisheng_memory_item_7"


async def test_ac58_upsert_and_search_carry_tenant_and_user(stubs, make_ctx):
    ctx = make_ctx()
    model_id = await stubs.index.upsert(ctx, "i1", "用户喜欢爬山")
    assert model_id == "7" and stubs.names["milvus"] == "bisheng_memory_item_7"
    texts, metas, ids = stubs.es.added[0]
    assert metas[0] == {"tenant_id": ctx.tenant_id, "user_id": ctx.user_id, "item_id": "i1"} and ids == ["i1"]
    assert stubs.milvus.added[0][2][0]["tenant_id"] == ctx.tenant_id
    scope = build_scope_filter(ctx)
    hits = await stubs.index.keyword_search(scope, "爬山", 5)
    assert [h.item_id for h in hits] == ["i1"]
    flt = stubs.es.searches[0][2]
    assert {"term": {"metadata.tenant_id": ctx.tenant_id}} in flt and {"term": {"metadata.user_id": ctx.user_id}} in flt
    vhits = await stubs.index.vector_search(ctx, scope, "爬山", 5)
    assert [h.item_id for h in vhits] == ["i2"]
    assert stubs.milvus.searches[0][2] == f"tenant_id == {ctx.tenant_id} and user_id == {ctx.user_id}"


async def test_delete_targets_items(stubs, make_ctx):
    ctx = make_ctx()
    await stubs.index.upsert(ctx, "i1", "x")
    await stubs.index.delete(ctx, ["i1"])
    assert stubs.es.deleted[-1] == ["i1"]
    assert 'item_id in ["i1"]' in stubs.milvus.deleted[-1] and f"user_id == {ctx.user_id}" in stubs.milvus.deleted[-1]


async def test_no_embedding_model_is_unconfigured(make_ctx):
    async def _loader(ctx):
        return None, None

    idx = PlatformMemoryIndex(es_factory=StubES, milvus_factory=lambda n, e: StubMilvus(), embedding_loader=_loader)
    ctx = make_ctx()
    assert await idx.upsert(ctx, "i1", "x") is None  # keyword only
    with pytest.raises(VectorUnconfigured):
        await idx.vector_search(ctx, build_scope_filter(ctx), "x", 3)


async def test_embedding_timeout(monkeypatch, make_ctx):
    assert index_mod.EMBED_TIMEOUT_SECONDS == 3.0
    monkeypatch.setattr(index_mod, "EMBED_TIMEOUT_SECONDS", 0.01)

    async def _loader(ctx):
        return "7", StubEmbeddings(delay=0.5)

    idx = PlatformMemoryIndex(es_factory=StubES, milvus_factory=lambda n, e: StubMilvus(), embedding_loader=_loader)
    ctx = make_ctx()
    with pytest.raises(asyncio.TimeoutError):
        await idx.vector_search(ctx, build_scope_filter(ctx), "x", 3)


async def test_default_embedding_loader_uses_memory_app_type(monkeypatch, make_ctx):
    captured = {}

    async def fake_embedding(**kwargs):
        captured.update(kwargs)
        return StubEmbeddings()

    monkeypatch.setattr(
        index_mod.LLMService, "aget_knowledge_llm", AsyncMock(return_value=SimpleNamespace(embedding_model_id=12))
    )
    monkeypatch.setattr(index_mod.LLMService, "get_bisheng_embedding", fake_embedding)
    ctx = make_ctx()
    model_id, emb = await index_mod.default_embedding_loader(ctx)
    assert model_id == "12" and emb is not None
    assert captured["user_id"] == ctx.user_id and captured["app_type"] == ApplicationTypeEnum.MEMORY
    assert captured["model_id"] == 12


async def test_ac45_consolidation_call_identity_and_model(monkeypatch, make_ctx):
    captured = {}

    class FakeLLM:
        async def ainvoke(self, prompt):
            return SimpleNamespace(content='{"operations": []}')

    async def fake_llm(**kwargs):
        captured.update(kwargs)
        return FakeLLM()

    monkeypatch.setattr(llm_mod.LLMService, "get_bisheng_llm", fake_llm)
    monkeypatch.setattr(llm_mod, "resolve_memory_model_id", AsyncMock(return_value=33))
    ctx = make_ctx()
    out = await llm_mod.PlatformMemoryLLM().consolidate(ctx, "prompt")
    assert out == '{"operations": []}'
    assert captured["model_id"] == 33 and captured["user_id"] == ctx.user_id
    assert captured["app_type"] == ApplicationTypeEnum.MEMORY and captured["app_id"] == "memory"


async def test_consolidation_rejection_is_identifiable(monkeypatch, make_ctx):
    class Rejecting:
        async def ainvoke(self, prompt):
            raise RuntimeError("quota exceeded")

    monkeypatch.setattr(llm_mod.LLMService, "get_bisheng_llm", AsyncMock(return_value=Rejecting()))
    monkeypatch.setattr(llm_mod, "resolve_memory_model_id", AsyncMock(return_value=33))
    with pytest.raises(llm_mod.MemoryLLMCallError):
        await llm_mod.PlatformMemoryLLM().consolidate(make_ctx(), "p")
    monkeypatch.setattr(llm_mod, "resolve_memory_model_id", AsyncMock(side_effect=MemoryNoModelError()))
    with pytest.raises(MemoryNoModelError):
        await llm_mod.PlatformMemoryLLM().consolidate(make_ctx(), "p")


def test_memory_calls_not_governed_by_personal_credits(monkeypatch):
    """Decision 18: the personal-credit gate only covers daily_chat and linsight."""
    from bisheng.dsh.domain.services import chat_credits

    monkeypatch.setattr(
        "bisheng.common.services.config_service.settings", SimpleNamespace(dsh=SimpleNamespace(enabled=True))
    )
    assert chat_credits.governed(SimpleNamespace(app_type=ApplicationTypeEnum.MEMORY.value)) is False
    assert chat_credits.governed(SimpleNamespace(app_type="daily_chat")) is True


def test_factory_wires_real_implementations():
    from bisheng.memory.domain.services import factory
    from bisheng.memory.domain.services.detail_store import MinioDetailStore
    from bisheng.memory.domain.services.kv import RedisKV

    factory.reset()
    svc = factory.get_memory_service()
    assert isinstance(svc.index, PlatformMemoryIndex)
    assert isinstance(svc.details, MinioDetailStore)
    assert isinstance(svc.kv, RedisKV)
    assert isinstance(factory.get_memory_llm(), llm_mod.PlatformMemoryLLM)
    assert factory.get_search_service().index is svc.index
    assert factory.get_resident_service().kv is svc.kv
    factory.reset()
