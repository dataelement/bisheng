from types import SimpleNamespace
from unittest.mock import MagicMock

from bisheng.common.constants.vectorstore_metadata import KNOWLEDGE_RAG_METADATA_SCHEMA
from bisheng.worker.knowledge import rebuild_knowledge_worker


def test_rebuild_uses_explicit_milvus_metadata_schema(monkeypatch):
    knowledge = SimpleNamespace(id=3124, index_name="knowledge-index", collection_name="knowledge-collection")
    embeddings = MagicMock()
    embeddings.embed_query.return_value = [0.1, 0.2]
    es_client = SimpleNamespace(client=SimpleNamespace(indices=SimpleNamespace(exists=lambda index: True)))
    vector_client = MagicMock()
    init_milvus = MagicMock(return_value=vector_client)

    monkeypatch.setattr(
        rebuild_knowledge_worker.KnowledgeRag,
        "init_knowledge_es_vectorstore_sync",
        lambda knowledge: es_client,
    )
    monkeypatch.setattr(
        rebuild_knowledge_worker.LLMService,
        "get_bisheng_knowledge_embedding_sync",
        lambda model_id, invoke_user_id: embeddings,
    )
    monkeypatch.setattr(
        rebuild_knowledge_worker.KnowledgeRag,
        "init_knowledge_milvus_vectorstore_sync",
        init_milvus,
    )

    result = rebuild_knowledge_worker._rebuild_embeddings(
        knowledge=knowledge,
        files=[],
        new_model_id=884,
        invoke_user_id=1,
    )

    assert result == ([], [])
    init_milvus.assert_called_once_with(
        invoke_user_id=1,
        knowledge=knowledge,
        embeddings=embeddings,
        metadata_schemas=KNOWLEDGE_RAG_METADATA_SCHEMA,
    )
