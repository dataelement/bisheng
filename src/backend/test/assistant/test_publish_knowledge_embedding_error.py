from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.api.services import assistant as assistant_module
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.knowledge.domain import knowledge_rag as rag_module


@pytest.mark.parametrize("failure", [AttributeError("missing model"), RuntimeError("provider unavailable")])
async def test_publish_reports_the_knowledge_base_with_unavailable_embedding(failure):
    knowledge = SimpleNamespace(id=4188, name="Audio library", model="889", collection_name="test")

    async def initialize():
        await rag_module.KnowledgeRag.init_knowledge_milvus_vectorstore(7, knowledge)

    assistant = SimpleNamespace(id="assistant-test", status=1)
    agent = SimpleNamespace(init_assistant=initialize)
    with (
        patch.object(assistant_module.AssistantDao, "get_one_assistant", return_value=assistant),
        patch.object(assistant_module.AssistantDao, "update_assistant") as save,
        patch.object(assistant_module, "require_business_action", new=AsyncMock()),
        patch.object(assistant_module, "AssistantAgent", return_value=agent),
        patch.object(rag_module.KnowledgeRag, "_get_knowledge", new=AsyncMock(return_value=knowledge)),
        patch.object(rag_module.LLMService, "get_bisheng_knowledge_embedding", new=AsyncMock(side_effect=failure)),
    ):
        with pytest.raises(BaseErrorCode) as caught:
            await assistant_module.AssistantService.update_status(
                MagicMock(), SimpleNamespace(user_id=7), assistant.id, 2
            )

    response = caught.value.return_resp_instance()
    assert response.status_code == 10425
    assert response.data["knowledge_name"] == "Audio library"
    assert "Audio library" in response.status_message
    assert caught.value.__cause__.__cause__ is failure
    assert assistant.status == 1
    save.assert_not_called()


async def test_vector_store_failure_is_not_reported_as_embedding_unavailable():
    knowledge = SimpleNamespace(id=4188, name="Audio library", model="889", collection_name="test")
    failure = RuntimeError("Milvus unavailable")
    with (
        patch.object(rag_module.KnowledgeRag, "_get_knowledge", new=AsyncMock(return_value=knowledge)),
        patch.object(rag_module.LLMService, "get_bisheng_knowledge_embedding", new=AsyncMock(return_value=MagicMock())),
        patch.object(rag_module.KnowledgeRag, "init_milvus_vectorstore", side_effect=failure),
    ):
        with pytest.raises(RuntimeError) as caught:
            await rag_module.KnowledgeRag.init_knowledge_milvus_vectorstore(7, knowledge)
    assert caught.value is failure


async def test_caller_supplied_embedding_does_not_require_model_resolution():
    knowledge = SimpleNamespace(id=4188, name="Audio library", model="889", collection_name="test")
    embeddings = MagicMock()
    vector_store = MagicMock()
    with (
        patch.object(rag_module.KnowledgeRag, "_get_knowledge", new=AsyncMock(return_value=knowledge)),
        patch.object(rag_module.LLMService, "get_bisheng_knowledge_embedding", new=AsyncMock()) as resolve,
        patch.object(rag_module.KnowledgeRag, "init_milvus_vectorstore", return_value=vector_store),
    ):
        result = await rag_module.KnowledgeRag.init_knowledge_milvus_vectorstore(7, knowledge, embeddings=embeddings)
    assert result is vector_store
    resolve.assert_not_awaited()
