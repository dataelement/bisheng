"""E+ knowledge retrieval must not create internal assistant citations."""

from __future__ import annotations

import json
from unittest.mock import patch

from langchain_core.documents import Document
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from bisheng.api.services.assistant_agent import AssistantCitationToolWrapper
from bisheng.assistant.domain.schemas.execution import AssistantRobotScope
from bisheng.citation.domain.services.citation_prompt_helper import CitationRegistryCollector
from bisheng.eplus.domain.services.robot_space_retrieval import RobotKnowledgeRagTool, RobotSpaceRetrieverTool


class _BoundSpacePolicy:
    async def retrieve(self, query: str, *, expected_scope: AssistantRobotScope, **kwargs) -> list[Document]:
        assert query == "营业额"
        assert expected_scope.space_ids == (11,)
        return [
            Document(
                page_content="2025 年营业额为 10 亿元",
                metadata={
                    "document_id": 101,
                    "knowledge_id": 11,
                    "document_name": "年度报告.pdf",
                    "chunk_index": 0,
                    "access_scope": "robot_bound",
                },
            )
        ]


async def test_robot_bound_knowledge_returns_text_without_registering_internal_citations():
    scope = AssistantRobotScope(bot_config_id=3, space_ids=(11,), scope_version=7)
    retriever = RobotSpaceRetrieverTool(policy=_BoundSpacePolicy(), expected_scope=scope)
    robot_tool = RobotKnowledgeRagTool(
        name="eplus_robot_knowledge",
        description="robot knowledge",
        llm=FakeListChatModel(responses=["unused"]),
        knowledge_retriever_tool=retriever,
    )
    collector = CitationRegistryCollector()
    wrapped = AssistantCitationToolWrapper.wrap(robot_tool, collector)
    wrapped.kb_name_by_id = {"11": "绑定空间"}

    with (
        patch(
            "bisheng.citation.domain.services.citation_registry_service.CitationRegistryService._load_knowledge_names",
            return_value={11: "绑定空间"},
        ),
        patch(
            "bisheng.api.services.assistant_agent.KnowledgeUtils.format_retrieved_chunk",
            lambda doc, kb_name: f"{kb_name}/{doc.metadata['document_name']}: {doc.page_content}",
            create=True,
        ),
    ):
        result = await wrapped.ainvoke({"query": "营业额"})

    payload = json.loads(result)
    assert payload["is_complete_file_list"] is False
    assert payload["sources"] == [
        {"file_id": 101, "file_name": "年度报告.pdf", "space_id": 11, "space_name": "绑定空间"}
    ]
    assert payload["chunks"][0]["source_file_id"] == 101
    assert payload["chunks"][0]["content"] == "2025 年营业额为 10 亿元"
    assert "citation_key" not in result
    assert collector.list_items() == []


async def test_robot_source_dedup_keeps_distinct_chunks_and_same_name_files_separate():
    scope = AssistantRobotScope(bot_config_id=3, space_ids=(11, 12), scope_version=7)
    retriever = RobotSpaceRetrieverTool(policy=_BoundSpacePolicy(), expected_scope=scope)
    tool = RobotKnowledgeRagTool(
        name="eplus_robot_knowledge",
        description="robot knowledge",
        llm=FakeListChatModel(responses=["unused"]),
        knowledge_retriever_tool=retriever,
    )
    wrapped = AssistantCitationToolWrapper.wrap(tool, CitationRegistryCollector())
    wrapped.kb_name_by_id = {"11": "A", "12": "B"}
    docs = [
        Document(
            page_content=text,
            metadata={"document_id": fid, "knowledge_id": sid, "document_name": "same.csv", "chunk_index": index},
        )
        for fid, sid, index, text in [(101, 11, 0, "first"), (101, 11, 1, "second"), (102, 12, 0, "third")]
    ]
    with patch(
        "bisheng.api.services.assistant_agent.KnowledgeUtils.format_retrieved_chunk",
        lambda doc, name: f"{name}/{doc.metadata['document_name']}: {doc.page_content}",
        create=True,
    ):
        payload = json.loads(wrapped._format_knowledge_results(docs))

    assert [s["file_id"] for s in payload["sources"]] == [101, 102]
    assert [s["space_name"] for s in payload["sources"]] == ["A", "B"]
    assert [c["source_file_id"] for c in payload["chunks"]] == [101, 101, 102]
    assert [c["content"] for c in payload["chunks"]] == ["first", "second", "third"]
    assert "space_type" not in payload["sources"][0]


async def test_robot_wrapper_forwards_exact_file_constraint_to_real_retrieval_step():
    class Policy:
        async def retrieve(self, query, **kwargs):
            assert kwargs["file_name"] == "年度报告.pdf"
            return []

    retriever = RobotSpaceRetrieverTool(policy=Policy(), expected_scope=AssistantRobotScope(3, (11,), 1))
    tool = RobotKnowledgeRagTool(
        name="eplus_robot_knowledge",
        description="robot knowledge",
        llm=FakeListChatModel(responses=["unused"]),
        knowledge_retriever_tool=retriever,
    )
    wrapped = AssistantCitationToolWrapper.wrap(tool, CitationRegistryCollector())
    payload = json.loads(await wrapped.ainvoke({"query": "归属", "file_name": "年度报告.pdf"}))
    assert payload["sources"] == []
    assert payload["chunks"] == []
    assert payload["is_complete_file_list"] is False


async def test_robot_wrapper_forwards_topic_filename_query_to_real_retrieval_step():
    class Policy:
        async def retrieve(self, query, **kwargs):
            assert kwargs["file_name_query"] == "深圳市 医学研究"
            assert kwargs["file_name"] is None
            return []

    retriever = RobotSpaceRetrieverTool(policy=Policy(), expected_scope=AssistantRobotScope(3, (11,), 1))
    tool = RobotKnowledgeRagTool(
        name="eplus_robot_knowledge",
        description="robot knowledge",
        llm=FakeListChatModel(responses=["unused"]),
        knowledge_retriever_tool=retriever,
    )
    wrapped = AssistantCitationToolWrapper.wrap(tool, CitationRegistryCollector())
    payload = json.loads(await wrapped.ainvoke({"query": "有哪些文件", "file_name_query": "深圳市 医学研究"}))
    assert payload["sources"] == []
