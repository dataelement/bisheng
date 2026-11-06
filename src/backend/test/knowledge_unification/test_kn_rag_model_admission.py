"""Actual RAG factories consume current full model source, not a stale caller row.

覆盖 AC: AC-37, AC-68, AC-71, AC-79, AC-87, AC-88, AC-89, AC-91, AC-92.
Knowledge/Core/Model SQL is real. Provider/vector transports and old DAO list
loading are isolated doubles; no network or middleware process is touched.
"""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.errcode.knowledge import (
    KnowledgeOperationPlanConflictError,
    ReferenceCoverageNotReadyError,
    ResourceReferenceInvalidError,
)
from bisheng.core.ai import FakeEmbeddings
from bisheng.knowledge.application.model_reference import KnowledgeModelReferenceApplication
from bisheng.knowledge.domain import knowledge_rag as module
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.llm.domain.models.llm_server import LLMModel
from bisheng.permission.application.identity import reset_current_permission_actor, set_current_permission_actor
from test.knowledge_unification import test_kn_model_source as fixtures

store = fixtures.store
tenant = fixtures.tenant
business = fixtures.business
admission = fixtures.admission


@pytest.fixture
async def rag(admission, monkeypatch):
    context, runtime, _, _ = admission
    async with context.sessions() as session, session.begin():
        await session.execute(
            sa.update(Knowledge)
            .where(Knowledge.id == 40, Knowledge.tenant_id == 101)
            .values(index_name="actual_index", collection_name="actual_collection")
        )
    monkeypatch.setattr(module, "get_knowledge_model_read_runtime_sync", lambda: runtime, raising=False)
    monkeypatch.setattr(module, "get_knowledge_model_read_runtime", AsyncMock(return_value=runtime), raising=False)
    monkeypatch.setattr(module.LLMService, "get_bisheng_knowledge_embedding_sync", Mock(return_value=FakeEmbeddings()))
    monkeypatch.setattr(module.LLMService, "get_bisheng_knowledge_embedding", AsyncMock(return_value=FakeEmbeddings()))
    monkeypatch.setattr(module.MilvusFactory, "init_vectorstore", Mock(return_value=Mock(name="actual-vector")))
    monkeypatch.setattr(module.ElasticsearchFactory, "init_vectorstore_sync", Mock(return_value=Mock(name="actual-es")))
    monkeypatch.setattr(
        module.ElasticsearchFactory, "init_vectorstore", Mock(return_value=Mock(name="actual-async-es"))
    )
    stale = Knowledge(
        id=40,
        tenant_id=101,
        name="stale",
        type=3,
        model="33",
        index_name="wrong_index",
        collection_name="wrong_collection",
    )
    monkeypatch.setattr(module.KnowledgeDao, "get_list_by_ids", Mock(return_value=[stale]))
    monkeypatch.setattr(module.KnowledgeDao, "aget_list_by_ids", AsyncMock(return_value=[stale]))
    return context, stale


@pytest.mark.parametrize("native", [False, True])
async def test_milvus_consumes_current_business_model_and_index_in_both_modes(rag, native):
    context, stale = rag
    if native:
        await asyncio.to_thread(
            KnowledgeRag.init_knowledge_milvus_vectorstore_sync, 7, knowledge=stale, login_user=context.user
        )
        module.LLMService.get_bisheng_knowledge_embedding_sync.assert_called_once_with(model_id=11, invoke_user_id=7)
    else:
        await KnowledgeRag.init_knowledge_milvus_vectorstore(7, knowledge=stale, login_user=context.user)
        module.LLMService.get_bisheng_knowledge_embedding.assert_awaited_once_with(model_id=11, invoke_user_id=7)
    assert module.MilvusFactory.init_vectorstore.call_args.args[0] == "actual_collection"
    assert "login_user" not in module.MilvusFactory.init_vectorstore.call_args.kwargs
    assert stale.model == "33" and stale.collection_name == "wrong_collection"


@pytest.mark.parametrize("native", [False, True])
async def test_es_constructor_uses_current_index_and_checks_the_complete_source(rag, native):
    context, stale = rag
    if native:
        await asyncio.to_thread(
            KnowledgeRag.init_knowledge_es_vectorstore_sync, knowledge=stale, login_user=context.user
        )
        factory = module.ElasticsearchFactory.init_vectorstore_sync
    else:
        await KnowledgeRag.init_knowledge_es_vectorstore(knowledge=stale, login_user=context.user)
        factory = module.ElasticsearchFactory.init_vectorstore
    assert factory.call_args.args[0] == "actual_index"
    assert "login_user" not in factory.call_args.kwargs


@pytest.mark.parametrize("native", [False, True])
async def test_provided_fake_embeddings_do_not_bypass_invalid_full_model_source(rag, native):
    context, stale = rag
    async with context.sessions() as session, session.begin():
        await session.execute(sa.delete(LLMModel).where(LLMModel.id == 11, LLMModel.tenant_id == 101))
    with pytest.raises(ResourceReferenceInvalidError):
        if native:
            await asyncio.to_thread(
                KnowledgeRag.init_knowledge_milvus_vectorstore_sync, 7, knowledge=stale, embeddings=FakeEmbeddings()
            )
        else:
            await KnowledgeRag.init_knowledge_milvus_vectorstore(7, knowledge=stale, embeddings=FakeEmbeddings())
    module.MilvusFactory.init_vectorstore.assert_not_called()


@pytest.mark.parametrize("native", [False, True])
async def test_knowledge_auth_off_keeps_its_original_upstream_rule_without_new_kn_visible(rag, native, monkeypatch):
    fixtures.owner_module.require_business_action.side_effect = UnAuthorizedError()
    permitted = Mock(side_effect=AssertionError("knowledge_auth=False must not add a filter"))
    monkeypatch.setattr(KnowledgeRag, "_get_usable_knowledge", permitted)
    monkeypatch.setattr(KnowledgeRag, "_aget_usable_knowledge", permitted)
    actor_token = set_current_permission_actor(None)
    try:
        if native:
            result = await asyncio.to_thread(
                KnowledgeRag.get_multi_knowledge_vectorstore_sync, 7, [40], check_auth=False, include_es=False
            )
        else:
            result = await KnowledgeRag.get_multi_knowledge_vectorstore(7, [40], check_auth=False, include_es=False)
        assert result[40]["milvus"] is module.MilvusFactory.init_vectorstore.return_value
        assert result[40]["knowledge"].model == "11"
        permitted.assert_not_called()
        fixtures.owner_module.require_business_action.assert_not_awaited()
    finally:
        reset_current_permission_actor(actor_token)


async def test_async_provider_unification_error_is_not_laundered_as_provider_unavailability(rag):
    context, stale = rag
    error = ReferenceCoverageNotReadyError(reason="default_source_not_ready")
    module.LLMService.get_bisheng_knowledge_embedding.side_effect = error
    with pytest.raises(ReferenceCoverageNotReadyError) as actual:
        await KnowledgeRag.init_knowledge_milvus_vectorstore(7, knowledge=stale, login_user=context.user)
    assert actual.value is error
    module.MilvusFactory.init_vectorstore.assert_not_called()


@pytest.mark.parametrize("native", [False, True])
async def test_original_knowledge_auth_filter_still_excludes_unauthorized_targets(rag, native, monkeypatch):
    check = Mock(return_value=[]) if native else AsyncMock(return_value=[])
    monkeypatch.setattr(KnowledgeRag, "_get_usable_knowledge" if native else "_aget_usable_knowledge", check)
    if native:
        result = await asyncio.to_thread(
            KnowledgeRag.get_multi_knowledge_vectorstore_sync, 7, [40], user_name="visitor"
        )
        check.assert_called_once_with("visitor", [40])
    else:
        result = await KnowledgeRag.get_multi_knowledge_vectorstore(7, [40], user_name="visitor")
        check.assert_awaited_once_with("visitor", [40])
    assert result == {}
    module.MilvusFactory.init_vectorstore.assert_not_called()


@pytest.mark.parametrize("native", [False, True])
async def test_keyword_only_current_retrieval_cannot_bypass_invalid_pending_model(rag, native):
    context, stale = rag
    async with context.sessions() as session:
        plan = await KnowledgeModelReferenceApplication.aprepare_model_change(session, 40, 12, login_user=context.user)
        await KnowledgeModelReferenceApplication.aapply_model_change(session, plan)
        await session.commit()
    async with context.sessions() as session, session.begin():
        await session.execute(sa.delete(LLMModel).where(LLMModel.id == 12, LLMModel.tenant_id == 101))
    with pytest.raises(ResourceReferenceInvalidError):
        if native:
            await asyncio.to_thread(KnowledgeRag.init_knowledge_es_vectorstore_sync, knowledge=stale)
        else:
            await KnowledgeRag.init_knowledge_es_vectorstore(knowledge=stale)
    module.ElasticsearchFactory.init_vectorstore.assert_not_called()
    module.ElasticsearchFactory.init_vectorstore_sync.assert_not_called()


@pytest.mark.parametrize("native", [False, True])
async def test_stale_generation_and_conflicting_resource_ids_fail_before_any_vector_io(rag, native):
    _, stale = rag
    with pytest.raises(KnowledgeOperationPlanConflictError):
        if native:
            await asyncio.to_thread(
                KnowledgeRag.init_knowledge_milvus_vectorstore_sync,
                7,
                knowledge=stale,
                expected_index_generation="obsolete",
            )
        else:
            await KnowledgeRag.init_knowledge_milvus_vectorstore(
                7, knowledge=stale, expected_index_generation="obsolete"
            )
    with pytest.raises(ResourceReferenceInvalidError):
        if native:
            await asyncio.to_thread(
                KnowledgeRag.init_knowledge_milvus_vectorstore_sync, 7, knowledge=stale, knowledge_id=41
            )
        else:
            await KnowledgeRag.init_knowledge_milvus_vectorstore(7, knowledge=stale, knowledge_id=41)
    module.MilvusFactory.init_vectorstore.assert_not_called()
