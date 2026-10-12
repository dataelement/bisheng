"""Observe actual robot tool results without changing model-visible bytes."""

import json
from unittest.mock import patch

import pytest
from langchain_core.documents import Document
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from bisheng.api.services.assistant_agent import AssistantCitationToolWrapper
from bisheng.assistant.domain.schemas.execution import AssistantRobotScope
from bisheng.citation.domain.services.citation_prompt_helper import CitationRegistryCollector
from bisheng.eplus.domain.services.robot_space_retrieval import RobotKnowledgeRagTool, RobotSpaceRetrieverTool
from bisheng.eplus.infrastructure.debug_trace import DebugTrace, observe_robot_tool


class Policy:
    async def retrieve(self, query, **kwargs):
        if query == "fail":
            raise RuntimeError("sensitive provider response")
        if query == "empty":
            return []
        return [
            Document(
                page_content="content", metadata={"knowledge_id": k, "document_id": d, "document_name": "same.csv"}
            )
            for k, d in [(11, 101), (12, 102)]
        ]


def wrapper():
    retriever = RobotSpaceRetrieverTool(policy=Policy(), expected_scope=AssistantRobotScope(3, (11, 12), 1))
    inner = RobotKnowledgeRagTool(
        name="eplus_robot_knowledge",
        description="real description",
        llm=FakeListChatModel(responses=["unused"]),
        knowledge_retriever_tool=retriever,
    )
    wrapped = AssistantCitationToolWrapper.wrap(inner, CitationRegistryCollector())
    wrapped.kb_name_by_id = {"11": "A", "12": "B"}
    return wrapped


async def test_observation_preserves_schema_result_and_separate_metadata():
    trace = DebugTrace()
    original = wrapper()
    observed = observe_robot_tool(original, trace)
    assert observed.name == original.name
    assert observed.description == original.description
    assert observed.args_schema == original.args_schema
    with patch(
        "bisheng.api.services.assistant_agent.KnowledgeUtils.format_retrieved_chunk",
        lambda doc, name: f"{name}/{doc.metadata['document_name']}",
        create=True,
    ):
        result = await observed.ainvoke({"query": "reformulated"})
        await observed.ainvoke({"query": "empty"})
    payload = json.loads(result)
    assert payload["sources"] == [
        {"file_id": 101, "file_name": "same.csv", "space_id": 11, "space_name": "A"},
        {"file_id": 102, "file_name": "same.csv", "space_id": 12, "space_name": "B"},
    ]
    assert [e["type"] for e in trace.events] == ["tool_start", "tool_end", "tool_start", "tool_end"]
    assert trace.events[0]["data"]["query"] == "reformulated"
    end = trace.events[1]["data"]
    assert end["model_tool_output"] == result
    assert [m["document_id"] for m in end["retrieval_metadata"]] == [101, 102]
    assert payload["chunks"][0]["source_file_id"] == 101
    assert json.loads(trace.events[3]["data"]["model_tool_output"])["sources"] == []


async def test_failed_tool_is_visible_without_exception_payload():
    trace = DebugTrace()
    observed = observe_robot_tool(wrapper(), trace)
    with pytest.raises(RuntimeError) as failure:
        await observed.ainvoke({"query": "fail"})
    assert "sensitive" not in str(failure.value)
    assert trace.events[-1]["type"] == "tool_error"
    assert trace.events[-1]["data"]["error_type"] == "RuntimeError"
    assert "sensitive" not in json.dumps(trace.events)


def test_trace_limit_fails_instead_of_returning_truncated_results():
    trace = DebugTrace(max_bytes=100)
    with pytest.raises(ValueError):
        trace.emit("tool_end", {"model_tool_output": "x" * 200})
    assert trace.events == []


async def test_observed_and_formal_tools_use_the_real_formatter_byte_for_byte(monkeypatch):
    import importlib.util
    from pathlib import Path

    import bisheng.api.services.assistant_agent as agent_module

    source = Path(agent_module.__file__).parents[2] / "knowledge/domain/services/knowledge_utils.py"
    spec = importlib.util.spec_from_file_location("eplus_actual_knowledge_utils", source)
    actual_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(actual_module)
    monkeypatch.setattr(agent_module, "KnowledgeUtils", actual_module.KnowledgeUtils)
    formal = wrapper()
    trace = DebugTrace()
    observed = observe_robot_tool(wrapper(), trace)
    formal_output = await formal.ainvoke({"query": "search"})
    observed_output = await observed.ainvoke({"query": "search"})
    assert formal_output == observed_output == trace.events[-1]["data"]["model_tool_output"]
    payload = json.loads(observed_output)
    assert [s["space_id"] for s in payload["sources"]] == [11, 12]
    assert [s["space_name"] for s in payload["sources"]] == ["A", "B"]
    assert [s["file_name"] for s in payload["sources"]] == ["same.csv", "same.csv"]
    assert [s["file_id"] for s in payload["sources"]] == [101, 102]
