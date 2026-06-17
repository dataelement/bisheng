"""SearchKnowledgeBase whitelist enforcement (C4 permission isolation).

Task mode advertises the user's accessible knowledge bases in the prompt, but a
model can hallucinate or be coaxed into an arbitrary ``knowledge_id``. Without a
hard check the tool would query that id directly via ``KnowledgeDao.query_by_id``
and leak another tenant's / unauthorised KB content. These tests pin that the
tool only searches ids inside the injected whitelist (the user-visible KB ids +
this session's uploaded file ids).
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from bisheng.tool.domain.langchain.linsight_knowledge import SearchKnowledgeBase


async def test_rejects_knowledge_id_outside_whitelist(monkeypatch: pytest.MonkeyPatch):
    """An id not in the whitelist must be refused WITHOUT touching the backend."""
    tool = SearchKnowledgeBase(allowed_knowledge_ids={"287"})

    search_kb = AsyncMock(return_value="should-not-be-called")
    search_file = AsyncMock(return_value="should-not-be-called")
    monkeypatch.setattr(SearchKnowledgeBase, "search_knowledge", search_kb)
    monkeypatch.setattr(SearchKnowledgeBase, "search_linsight_file", search_file)

    result = await tool._arun(query="机密", knowledge_id="999")

    payload = json.loads(result)
    assert payload["状态"] in {"无权限", "无结果"}
    search_kb.assert_not_awaited()
    search_file.assert_not_awaited()


async def test_allows_whitelisted_numeric_kb_id(monkeypatch: pytest.MonkeyPatch):
    """A numeric id inside the whitelist routes to search_knowledge."""
    tool = SearchKnowledgeBase(allowed_knowledge_ids={"287"})

    search_kb = AsyncMock(return_value='{"状态": "成功"}')
    monkeypatch.setattr(SearchKnowledgeBase, "search_knowledge", search_kb)

    result = await tool._arun(query="问题", knowledge_id="287", limit=3)

    search_kb.assert_awaited_once()
    assert search_kb.await_args.args[1] == 287  # knowledge_id coerced to int
    assert json.loads(result)["状态"] == "成功"


async def test_allows_whitelisted_file_id(monkeypatch: pytest.MonkeyPatch):
    """A non-numeric id (uploaded file) inside the whitelist routes to file search."""
    tool = SearchKnowledgeBase(allowed_knowledge_ids={"abcd1234"})

    search_file = AsyncMock(return_value='{"状态": "成功"}')
    monkeypatch.setattr(SearchKnowledgeBase, "search_linsight_file", search_file)

    result = await tool._arun(query="问题", knowledge_id="abcd1234")

    search_file.assert_awaited_once()
    assert json.loads(result)["状态"] == "成功"


async def test_no_whitelist_is_unrestricted(monkeypatch: pytest.MonkeyPatch):
    """Back-compat: when no whitelist is injected the tool does not gate ids."""
    tool = SearchKnowledgeBase()  # allowed_knowledge_ids defaults to None

    search_kb = AsyncMock(return_value='{"状态": "成功"}')
    monkeypatch.setattr(SearchKnowledgeBase, "search_knowledge", search_kb)

    await tool._arun(query="问题", knowledge_id="287")

    search_kb.assert_awaited_once()
