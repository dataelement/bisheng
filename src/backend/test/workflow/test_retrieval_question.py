from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from bisheng.workflow.common.knowledge import RagUtils
from bisheng.workflow.common.retrieval_question import normalize_retrieval_question
from bisheng.workflow.nodes.knowledge_retriever.knowledge_retriever import KnowledgeRetriever
from bisheng.workflow.nodes.qa_retriever.qa_retriever import QARetrieverNode
from bisheng.workflow.nodes.rag.rag import RagNode


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ""),
        ("", ""),
        ("   ", ""),
        ([], ""),
        ({}, ""),
        ((), ""),
        (set(), ""),
        (" weather ", " weather "),
        (0, "0"),
        (False, "False"),
        (["weather"], "['weather']"),
        ({"question": "weather"}, "{'question': 'weather'}"),
    ],
)
def test_normalize_retrieval_question(value, expected):
    assert normalize_retrieval_question(value) == expected


def test_rag_utils_normalizes_resolved_questions_before_retrieval():
    node = object.__new__(RagUtils)
    node.node_params = {
        "user_question": [
            "input.empty",
            "input.number",
            "input.list",
        ]
    }
    values = {
        "input.empty": [],
        "input.number": 7,
        "input.list": ["weather"],
    }
    node.get_other_node_variable = values.__getitem__

    assert node.init_user_question() == ["", "7", "['weather']"]


@pytest.mark.parametrize("value", [None, "", "   ", [], {}, (), set()])
def test_qa_retriever_skips_retrieval_for_empty_questions(value):
    node = object.__new__(QARetrieverNode)
    node.id = "qa_retriever_test"
    node._user_question = "input.question"
    node.init_user_info = MagicMock()
    node._init_retriever = MagicMock()
    node.get_other_node_variable = MagicMock(return_value=value)
    node.graph_state = MagicMock()
    node._retriever = MagicMock()

    result = node._run("execution-id")

    assert result == {"retrieved_result": ""}
    node._init_retriever.assert_not_called()
    node._retriever.invoke.assert_not_called()
    node.graph_state.set_variable.assert_called_once_with(
        node.id,
        "$retrieved_result$",
        None,
    )


def test_qa_retriever_stringifies_non_string_question():
    node = object.__new__(QARetrieverNode)
    node.id = "qa_retriever_test"
    node._user_question = "input.question"
    node.init_user_info = MagicMock()
    node._init_retriever = MagicMock()
    node.get_other_node_variable = MagicMock(return_value=["weather"])
    node.graph_state = MagicMock()
    node._retriever = MagicMock()
    node._retriever.invoke.return_value = {"result": []}

    result = node._run("execution-id")

    assert result == {"retrieved_result": ""}
    node._retriever.invoke.assert_called_once_with({"query": "['weather']"})


def test_knowledge_retriever_skips_retriever_setup_for_empty_questions():
    node = object.__new__(KnowledgeRetriever)
    node.id = "knowledge_retriever_test"
    node._output_keys = ["retrieved_result"]
    node.init_user_question = MagicMock(return_value=[""])
    node.init_user_info = MagicMock()
    node.init_multi_retriever = MagicMock()
    node.init_rerank_model = MagicMock()
    node.retrieve_question = MagicMock()
    node.graph_state = MagicMock()

    with (
        patch(
            "bisheng.workflow.nodes.knowledge_retriever.knowledge_retriever.annotate_rag_documents_with_citations",
            return_value=[],
        ),
        patch(
            "bisheng.workflow.nodes.knowledge_retriever.knowledge_retriever.collect_rag_citation_registry_items",
            return_value=[],
        ),
        patch("bisheng.workflow.nodes.knowledge_retriever.knowledge_retriever.cache_citation_registry_items_sync"),
    ):
        result = node._run("execution-id")

    assert result == {"retrieved_result": []}
    node.init_multi_retriever.assert_not_called()
    node.init_rerank_model.assert_not_called()
    node.retrieve_question.assert_not_called()


def test_rag_node_skips_retrieval_for_empty_questions():
    node = object.__new__(RagNode)
    node.id = "rag_test"
    node.name = "RAG"
    node._llm = MagicMock()
    node._qa_prompt = MagicMock(input_variables=[])
    node._output_user = False
    node.callback_manager = MagicMock()
    node.graph_state = MagicMock()
    node._log_reasoning_content = {}
    node._log_source_documents = {}
    node.init_multi_retriever = MagicMock()
    node.init_rerank_model = MagicMock()
    node.retrieve_question = MagicMock()

    chain = MagicMock()
    chain.invoke.return_value = "answer"
    llm_callback = MagicMock(reasoning_content="")

    with (
        patch(
            "bisheng.workflow.nodes.rag.rag.create_stuff_documents_chain",
            return_value=chain,
        ),
        patch(
            "bisheng.workflow.nodes.rag.rag.annotate_rag_documents_with_citations",
            return_value=[],
        ),
        patch(
            "bisheng.workflow.nodes.rag.rag.collect_rag_citation_registry_items",
            return_value=[],
        ),
        patch("bisheng.workflow.nodes.rag.rag.cache_citation_registry_items_sync"),
        patch(
            "bisheng.workflow.nodes.rag.rag.LLMNodeCallbackHandler",
            return_value=llm_callback,
        ),
    ):
        result = node.rag_one_question("", "answer", "execution-id")

    assert result == "answer"
    node.init_multi_retriever.assert_not_called()
    node.init_rerank_model.assert_not_called()
    node.retrieve_question.assert_not_called()
    chain.invoke.assert_called_once()
