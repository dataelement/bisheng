"""Embedding errors keep their original diagnostic after full-source admission.

覆盖 AC: AC-37, AC-68, AC-71, AC-87, AC-88, AC-89, AC-91, AC-92.
Knowledge/Model/R2 SQL and their actual Core/ReadRuntime are exercised; the
provider and vector transports remain isolated. Assistant SQL is independent
in the same trusted tenant, retaining its original publish rollback assertions.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import sqlalchemy as sa

from bisheng.api.services import assistant as assistant_module
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError
from bisheng.knowledge.application import model_reference_read as read_module
from bisheng.knowledge.domain import knowledge_rag as rag_module
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from test.knowledge_unification import test_as_bindings as binding_fixtures
from test.knowledge_unification import test_kn_model_source as knowledge_fixtures

assistant_tenant = binding_fixtures.assistant_tenant
assistant_business = binding_fixtures.assistant_business
store = knowledge_fixtures.store
tenant = knowledge_fixtures.tenant
business = knowledge_fixtures.business
admission = knowledge_fixtures.admission


@pytest.fixture
async def knowledge_model_source(admission, monkeypatch):
    context, runtime, _, _ = admission
    async with context.sessions() as session, session.begin():
        await session.execute(
            sa.update(Knowledge)
            .where(Knowledge.id == 40, Knowledge.tenant_id == 101)
            .values(name="Audio library", index_name="audio-index", collection_name="audio-collection")
        )
    async with context.sessions() as session:
        knowledge = await read_module.KnowledgeModelReferenceRepository().aget(session, 40)
    # Production still goes through its actual factory and real Core. Only its
    # configured test instance differs; no admission/Owner result is fabricated.
    monkeypatch.setattr(read_module, "_runtime", runtime)
    return context, knowledge


async def remove_source_index(context):
    async with context.sessions() as session, session.begin():
        await session.execute(
            sa.delete(BusinessReferenceSet).where(
                BusinessReferenceSet.tenant_id == 101,
                BusinessReferenceSet.record_kind == "source",
                BusinessReferenceSet.source_type == "knowledge",
                BusinessReferenceSet.source_id == "40",
            )
        )


async def assert_publish_rolled_back(context, save):
    assistant, _, references, source = await binding_fixtures.inspect_business(context)
    assert assistant.status == 1 and source.effective and len(references) == 2
    save.assert_not_called()


@pytest.mark.parametrize("failure", [AttributeError("missing model"), RuntimeError("provider unavailable")])
async def test_publish_reports_the_knowledge_base_with_unavailable_embedding(
    failure, assistant_business, knowledge_model_source
):
    context = assistant_business
    await binding_fixtures.seed(context)
    _, knowledge = knowledge_model_source

    async def initialize():
        await rag_module.KnowledgeRag.init_knowledge_milvus_vectorstore(7, knowledge)

    agent = SimpleNamespace(init_assistant=initialize)
    with (
        patch.object(assistant_module.AssistantDao, "update_assistant") as save,
        patch.object(assistant_module, "require_business_action", new=AsyncMock()),
        patch.object(assistant_module, "AssistantAgent", return_value=agent),
        patch.object(
            rag_module.LLMService, "get_bisheng_knowledge_embedding", new=AsyncMock(side_effect=failure)
        ) as provider,
    ):
        with pytest.raises(BaseErrorCode) as caught:
            await assistant_module.AssistantService.update_status(context.request, context.user, "assistant-a", 2)

    response = caught.value.return_resp_instance()
    assert response.status_code == 10425
    assert response.data["knowledge_name"] == "Audio library"
    assert "Audio library" in response.status_message
    assert caught.value.__cause__.__cause__ is failure
    provider.assert_awaited_once_with(model_id=11, invoke_user_id=7)
    await assert_publish_rolled_back(context, save)


async def test_vector_store_failure_is_not_reported_as_embedding_unavailable(knowledge_model_source):
    _, knowledge = knowledge_model_source
    failure = RuntimeError("Milvus unavailable")
    with (
        patch.object(rag_module.LLMService, "get_bisheng_knowledge_embedding", new=AsyncMock(return_value=MagicMock())),
        patch.object(rag_module.KnowledgeRag, "init_milvus_vectorstore", side_effect=failure),
    ):
        with pytest.raises(RuntimeError) as caught:
            await rag_module.KnowledgeRag.init_knowledge_milvus_vectorstore(7, knowledge)
    assert caught.value is failure


@pytest.mark.parametrize("ready", [False, True])
async def test_caller_supplied_embedding_skips_provider_but_requires_complete_source(knowledge_model_source, ready):
    context, knowledge = knowledge_model_source
    if not ready:
        await remove_source_index(context)
    embeddings = MagicMock()
    vector_store = MagicMock()
    with (
        patch.object(rag_module.LLMService, "get_bisheng_knowledge_embedding", new=AsyncMock()) as resolve,
        patch.object(rag_module.KnowledgeRag, "init_milvus_vectorstore", return_value=vector_store) as vectors,
    ):
        if ready:
            result = await rag_module.KnowledgeRag.init_knowledge_milvus_vectorstore(
                7, knowledge, embeddings=embeddings
            )
            assert result is vector_store
            vectors.assert_called_once_with("audio-collection", embeddings)
        else:
            with pytest.raises(ReferenceCoverageNotReadyError):
                await rag_module.KnowledgeRag.init_knowledge_milvus_vectorstore(7, knowledge, embeddings=embeddings)
            vectors.assert_not_called()
    resolve.assert_not_awaited()


async def test_publish_does_not_wrap_unready_knowledge_references_as_embedding_error(
    assistant_business, knowledge_model_source
):
    context = assistant_business
    await binding_fixtures.seed(context)
    knowledge_context, knowledge = knowledge_model_source
    await remove_source_index(knowledge_context)

    async def initialize():
        await rag_module.KnowledgeRag.init_knowledge_milvus_vectorstore(7, knowledge)

    with (
        patch.object(assistant_module.AssistantDao, "update_assistant") as save,
        patch.object(assistant_module, "AssistantAgent", return_value=SimpleNamespace(init_assistant=initialize)),
        patch.object(rag_module.LLMService, "get_bisheng_knowledge_embedding", new=AsyncMock()) as provider,
        patch.object(rag_module.KnowledgeRag, "init_milvus_vectorstore") as vectors,
    ):
        with pytest.raises(ReferenceCoverageNotReadyError) as caught:
            await assistant_module.AssistantService.update_status(context.request, context.user, "assistant-a", 2)
    assert caught.value.return_resp_instance().status_code == 10994
    provider.assert_not_awaited()
    vectors.assert_not_called()
    await assert_publish_rolled_back(context, save)
