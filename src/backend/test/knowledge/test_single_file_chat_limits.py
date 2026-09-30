"""单文档问答的大量片段、权限复用及超时回归。"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.documents import Document
from langchain_core.messages import AIMessageChunk

from bisheng.common.errcode.knowledge_space import SpacePermissionDeniedError
from bisheng.common.stream_errors import StreamStageError
from bisheng.knowledge.domain.contracts.errors import SharedStorageContractError
from bisheng.knowledge.domain.contracts.retrieval_scope import CanonicalChunkHit
from bisheng.knowledge.domain.services import knowledge_space_chat_service as mod


def make_service():
    service = mod.KnowledgeSpaceChatService(request=MagicMock(), login_user=SimpleNamespace(user_id=42, tenant_id=1))
    service.retrieval_runtime = SimpleNamespace(
        config=SimpleNamespace(
            total_timeout_seconds=0.02,
            embedding_timeout_seconds=1,
            elasticsearch_timeout_seconds=1,
        ),
        embed_query=AsyncMock(return_value=[0.1]),
    )
    return service


def prepare_generation(monkeypatch, service, contents, budget=10):
    monkeypatch.setattr(mod, "MessageCategory", SimpleNamespace(STREAM="stream"))
    monkeypatch.setattr(mod, "logger", MagicMock())
    llm = MagicMock()

    async def stream(_inputs):
        yield AIMessageChunk(content="回答")

    llm.astream = MagicMock(side_effect=stream)
    service.get_space_llm_config = AsyncMock(
        return_value=(
            llm,
            SimpleNamespace(max_chunk_size=budget, system_prompt="system", user_prompt="{retrieved_file_content}"),
        )
    )
    service.get_history = AsyncMock(return_value=[])
    service.aretrieve_chunks = AsyncMock(return_value=[(1, Document(page_content=content)) for content in contents])
    monkeypatch.setattr(mod, "get_prompt_manager", AsyncMock())
    return llm


def single_file_stream(service):
    return service.space_rag(
        SimpleNamespace(chat_id="test", flow_id="space_1_file_10", name="已命名"),
        None,
        None,
        "明细",
        1,
        knowledge_id=1,
        target_file_ids=[10],
        preauthorized_file_ids={10},
    )


@pytest.mark.parametrize(
    "contents,expected",
    [
        (["甲" * 8, "乙" * 8], "甲" * 8 + "\n乙"),
        (["甲" * 100_000], "甲" * 10),
        (["甲", "乙"], "甲\n乙\n"),
    ],
    ids=["combined-budget", "oversized-chunk", "small-document"],
)
async def test_single_file_bounds_combined_retrieved_text(monkeypatch, contents, expected):
    service = make_service()
    llm = prepare_generation(monkeypatch, service, contents)
    stream = single_file_stream(service)
    try:
        await anext(stream)
    finally:
        await stream.aclose()
    inputs = llm.astream.call_args.args[0]
    assert inputs[-1].content == expected
    assert len(inputs[-1].content) <= 10


@pytest.mark.parametrize("stage", ["search", "authorization"])
async def test_single_file_timeout_cancels_retrieval_before_model(monkeypatch, shared_service, stage):
    service, reader = shared_service
    llm = prepare_generation(monkeypatch, service, [])
    del service.aretrieve_chunks
    service._is_shared_storage_active = AsyncMock(return_value=True)
    service.retrieval_runtime.config.total_timeout_seconds = 0.05
    cancelled = set()

    async def blocked(name):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.add(name)

    if stage == "search":
        reader.search_milvus = lambda **kwargs: blocked("milvus")
        reader.search_es = lambda **kwargs: blocked("es")
    else:
        service.department_file_view_access_service = MagicMock()
        service._require_portal_file_view_permission = lambda *args: blocked("authorization")

    stream = single_file_stream(service)
    try:
        with pytest.raises(StreamStageError) as error:
            await asyncio.wait_for(anext(stream), timeout=0.5)
        assert error.value.stage == "retrieval"
        assert isinstance(error.value.error, asyncio.TimeoutError)
        assert cancelled == ({"milvus", "es"} if stage == "search" else {"authorization"})
        llm.astream.assert_not_called()
    finally:
        await stream.aclose()


@pytest.fixture
def shared_service(monkeypatch):
    service = make_service()
    entry = SimpleNamespace(
        id=10,
        tenant_id=1,
        knowledge_id=1,
        file_type=1,
        file_name="large.xlsx",
        reference_document_id=100,
        entry_type="manager",
        entry_status="active",
        projection_status="ready",
        desired_content_generation=1,
        applied_content_generation=1,
        desired_entry_generation=1,
        applied_entry_generation=1,
    )
    document = SimpleNamespace(
        id=100,
        tenant_id=1,
        primary_version_id=200,
        lifecycle_status="active",
        content_generation=1,
    )
    service.file_repo = SimpleNamespace(
        find_by_ids=AsyncMock(return_value=[entry]),
        find_active_entries_for_documents=AsyncMock(return_value=[entry]),
        find_active_entries_for_documents_any_space=AsyncMock(return_value=[entry]),
    )
    service.doc_repo = SimpleNamespace(find_by_ids=AsyncMock(return_value=[document]))
    service.version_repo = MagicMock()
    service._knowledge_space_permission_service = SimpleNamespace(
        _require_read_permission=AsyncMock(),
        _get_effective_permission_ids=AsyncMock(return_value={"view_file"}),
    )
    hits = [
        CanonicalChunkHit(
            canonical_document_id=100,
            canonical_version_id=200,
            chunk_index=i,
            text=f"第{i}行",
            score=1,
            content_generation=1,
            membership_generation=1,
        )
        for i in range(100)
    ]
    reader = SimpleNamespace(
        search_milvus=AsyncMock(return_value=hits),
        search_es=AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        mod.KnowledgeDao, "aquery_by_id", AsyncMock(return_value=SimpleNamespace(id=1, tenant_id=1, type=3))
    )
    monkeypatch.setattr(
        "bisheng.knowledge.rag.shared_space_storage.aresolve_space_shared_routing",
        AsyncMock(return_value=SimpleNamespace(routing_version=1, collection_name="shared")),
    )
    monkeypatch.setattr(
        "bisheng.knowledge.rag.shared_space_storage.SharedSpaceStorageReader", MagicMock(return_value=reader)
    )
    monkeypatch.setattr(mod.LLMService, "aget_knowledge_default_embedding", AsyncMock(return_value=MagicMock()))
    monkeypatch.setattr("bisheng.core.search.elasticsearch.manager.get_es_connection", AsyncMock())
    return service, reader


async def retrieve(service):
    return await service._aretrieve_chunks_shared(
        query="明细",
        knowledge_base_ids=[1],
        kb_filters={1: {"file_ids": [10]}},
        top_k=100,
        max_content=15000,
        preauthorized_file_ids={10},
    )


@pytest.mark.parametrize("portal,allowed", [(True, True), (False, True), (False, False)])
async def test_large_file_authorizes_once_per_request_and_rechecks_next_request(shared_service, portal, allowed):
    service, _ = shared_service
    if portal:
        service.department_file_view_access_service = MagicMock()
        check = AsyncMock()
        service._require_portal_file_view_permission = check
    else:
        check = service._knowledge_space_permission_service._get_effective_permission_ids
        check.return_value = {"view_file"} if allowed else set()

    result = await retrieve(service)
    assert len(result) == (100 if allowed else 0)
    assert check.await_count == 1

    # 下一次请求必须重新判断权限, 不复用上次允许或拒绝的结论。
    if portal:
        check.side_effect = SpacePermissionDeniedError()
        with pytest.raises(SharedStorageContractError):
            await retrieve(service)
    else:
        check.return_value = set() if allowed else {"view_file"}
        result = await retrieve(service)
        assert len(result) == (0 if allowed else 100)
    assert check.await_count == 2
