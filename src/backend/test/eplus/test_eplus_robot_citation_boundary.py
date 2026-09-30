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

    chunks = json.loads(result)
    assert len(chunks) == 1
    assert "2025 年营业额为 10 亿元" in chunks[0]
    assert "年度报告.pdf" in chunks[0]
    assert "citation_key" not in chunks[0]
    assert collector.list_items() == []
