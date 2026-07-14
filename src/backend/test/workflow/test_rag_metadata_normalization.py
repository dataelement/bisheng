from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from langchain_core.documents import Document

from bisheng.workflow.common.knowledge import RagUtils


def test_mixed_metadata_shapes_do_not_break_multi_knowledge_retrieval():
    rag_utils = object.__new__(RagUtils)
    rag_utils._knowledge_type = "knowledge"
    rag_utils._multi_milvus_retriever = None
    rag_utils._multi_es_retriever = None
    rag_utils._max_chunk_size = 15000
    rag_utils._vector_weight = 0.5
    rag_utils._keyword_weight = 0.5
    rag_utils._rerank_model = None

    documents = [
        Document(
            page_content="business metadata",
            metadata={
                "document_id": 101,
                "knowledge_id": 1,
                "user_metadata": {"review_status": "approved"},
            },
        ),
        Document(
            page_content="time metadata",
            metadata={
                "document_id": 202,
                "knowledge_id": 2,
                "user_metadata": {"effective_time": 1_700_000_000},
            },
        ),
    ]
    retriever_tool = MagicMock()
    retriever_tool.invoke.return_value = documents
    database_files = [
        SimpleNamespace(id=101, user_metadata={"review_status": "approved"}),
        SimpleNamespace(
            id=202,
            user_metadata={
                "effective_time": {
                    "field_value": 1_700_000_000,
                    "field_type": "time",
                }
            },
        ),
    ]

    with (
        patch(
            "bisheng.workflow.common.knowledge.KnowledgeRetrieverTool",
            return_value=retriever_tool,
        ),
        patch(
            "bisheng.workflow.common.knowledge.KnowledgeFileDao.get_file_by_ids",
            return_value=database_files,
        ),
    ):
        result = rag_utils.retrieve_knowledge_question("question")

    assert result[0].metadata["user_metadata"]["review_status"] == "approved"
    assert result[1].metadata["user_metadata"]["effective_time"] == rag_utils.format_timestamp(1_700_000_000)
