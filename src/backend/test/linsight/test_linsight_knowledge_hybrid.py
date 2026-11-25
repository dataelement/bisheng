"""Deep research searches a knowledge base the way daily chat does (ES + Milvus, file permissions)."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.documents import Document

from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
from bisheng.tool.domain.langchain import linsight_knowledge as knowledge_tool
from bisheng.tool.domain.langchain.linsight_knowledge import SEARCH_MAX_CONTENT, SearchKnowledgeBase
from bisheng.workstation.domain.services.workstation_service import WorkStationService

USER = SimpleNamespace(user_id=7)


def _doc(i: int) -> Document:
    return Document(page_content=f"chunk {i}", metadata={"document_id": i, "chunk_index": i})


@pytest.fixture
def query_chunks(monkeypatch):
    mock = AsyncMock(return_value=([], [_doc(3), _doc(1), _doc(2)], []))
    monkeypatch.setattr(WorkStationService, "queryChunksFromDB", mock)
    monkeypatch.setattr(KnowledgeDao, "aquery_by_id", AsyncMock(return_value=SimpleNamespace(name="制度库")))
    formatted = AsyncMock(return_value="formatted")
    monkeypatch.setattr(SearchKnowledgeBase, "format_documents", formatted)
    return mock, formatted


async def test_search_runs_daily_retrieval_in_rank_order(query_chunks):
    mock, formatted = query_chunks
    tool = SearchKnowledgeBase(allowed_knowledge_ids={"42"}, login_user=USER)

    assert await tool.ainvoke({"query": "GB/T 9704", "knowledge_id": "42", "limit": 2}) == "formatted"

    args, kwargs = mock.await_args
    assert args[0] == "GB/T 9704"
    assert args[1].organization_knowledge_ids == [42]
    assert args[2] == SEARCH_MAX_CONTENT
    assert args[3] is USER
    assert kwargs == {"sort_by_source_and_index": False}
    docs = formatted.await_args.args[0]
    assert [d.metadata["document_id"] for d in docs] == [3, 1]
    assert formatted.await_args.kwargs == {"knowledge_id": 42, "knowledge_name": "制度库"}


async def test_whitelist_refusal_never_retrieves(query_chunks):
    mock, _ = query_chunks
    tool = SearchKnowledgeBase(allowed_knowledge_ids={"42"}, login_user=USER)

    raw = await tool.ainvoke({"query": "q", "knowledge_id": "43"})

    assert json.loads(raw)["状态"] == "无权限"
    mock.assert_not_awaited()


async def test_failure_without_chunks_is_a_soft_failure(monkeypatch):
    failure = {"id": 42, "name": "", "error": "No permission to use this knowledge base"}
    monkeypatch.setattr(WorkStationService, "queryChunksFromDB", AsyncMock(return_value=([], [], [failure])))
    tool = SearchKnowledgeBase(allowed_knowledge_ids={"42"}, login_user=USER)

    payload = json.loads(await tool.ainvoke({"query": "q", "knowledge_id": "42"}))

    assert payload == {"状态": "失败", "错误信息": "No permission to use this knowledge base"}


async def test_no_chunks_is_no_result(monkeypatch):
    monkeypatch.setattr(WorkStationService, "queryChunksFromDB", AsyncMock(return_value=([], [], [])))
    tool = SearchKnowledgeBase(allowed_knowledge_ids={"42"}, login_user=USER)

    assert json.loads(await tool.ainvoke({"query": "q", "knowledge_id": "42"}))["状态"] == "无结果"


async def test_missing_user_is_a_soft_failure(query_chunks):
    mock, _ = query_chunks
    tool = SearchKnowledgeBase(allowed_knowledge_ids={"42"})

    assert json.loads(await tool.ainvoke({"query": "q", "knowledge_id": "42"}))["状态"] == "失败"
    mock.assert_not_awaited()


async def test_init_linsight_tools_hands_the_user_to_the_tool():
    from bisheng.tool.domain.services.tool import ToolServices

    (tool,) = await ToolServices.init_linsight_tools(root_path="/tmp/x", allowed_knowledge_ids={"1"}, login_user=USER)
    assert tool.login_user is USER


async def test_task_builds_the_search_user_only_when_there_is_something_to_search(monkeypatch):
    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.linsight.domain.task_exec import LinsightWorkflowTask

    init = AsyncMock(return_value=USER)
    monkeypatch.setattr(UserPayload, "init_login_user", init)
    session = SimpleNamespace(user_id=7)

    assert await LinsightWorkflowTask._knowledge_search_user(session, set()) is None
    init.assert_not_awaited()
    assert await LinsightWorkflowTask._knowledge_search_user(session, {"1"}) is USER
    assert init.await_args.kwargs["user_id"] == 7


def test_module_no_longer_reads_milvus_directly():
    assert not hasattr(knowledge_tool, "KnowledgeRag")
