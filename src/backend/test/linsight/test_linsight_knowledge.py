"""SearchKnowledgeBase whitelist enforcement (C4 permission isolation).

Task mode advertises the user's accessible knowledge bases in the prompt, but a
model can hallucinate or be coaxed into an arbitrary ``knowledge_id``. Without a
hard check the tool would query that id directly via ``KnowledgeDao.query_by_id``
and leak another tenant's / unauthorised KB content. These tests pin that the
tool only searches ids inside the injected whitelist (the user-visible KB ids).

Scope: the tool retrieves ONLY knowledge bases / knowledge spaces. Uploaded
files are no longer searched here — the deepagents flow downloads each uploaded
file's parsed markdown into the agent workspace, so the agent reads them with
``ls`` / ``read_file`` instead. The legacy file-semantic-search branch is gone.
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
    monkeypatch.setattr(SearchKnowledgeBase, "search_knowledge", search_kb)

    result = await tool._arun(query="机密", knowledge_id="999")

    payload = json.loads(result)
    assert payload["状态"] in {"无权限", "无结果"}
    search_kb.assert_not_awaited()


async def test_allows_whitelisted_numeric_kb_id(monkeypatch: pytest.MonkeyPatch):
    """A numeric id inside the whitelist routes to search_knowledge."""
    tool = SearchKnowledgeBase(allowed_knowledge_ids={"287"})

    search_kb = AsyncMock(return_value='{"状态": "成功"}')
    monkeypatch.setattr(SearchKnowledgeBase, "search_knowledge", search_kb)

    result = await tool._arun(query="问题", knowledge_id="287", limit=3)

    search_kb.assert_awaited_once()
    assert search_kb.await_args.args[1] == 287  # knowledge_id coerced to int
    assert json.loads(result)["状态"] == "成功"


async def test_file_search_branch_removed():
    """Uploaded-file semantic search is no longer part of this tool.

    A non-numeric knowledge_id (the old file_id shape) must NOT trigger any file
    lookup — the method itself is gone — and the tool returns a soft error rather
    than raising. Files are read from the agent workspace via read_file now.
    """
    assert not hasattr(SearchKnowledgeBase, "search_linsight_file")

    tool = SearchKnowledgeBase()  # ungated, so no whitelist short-circuit
    result = await tool._arun(query="问题", knowledge_id="abcd1234")

    payload = json.loads(result)
    assert payload["状态"] in {"无结果", "失败"}


def test_description_scopes_to_kb_and_space_only():
    """The description must cover knowledge spaces and redirect files to read_file
    (not advertise in-tool file retrieval)."""
    desc = SearchKnowledgeBase().description
    assert "知识空间" in desc
    # Files are not searched here; the description steers the model to read_file.
    assert "read_file" in desc


async def test_no_whitelist_is_unrestricted(monkeypatch: pytest.MonkeyPatch):
    """Back-compat: when no whitelist is injected the tool does not gate ids."""
    tool = SearchKnowledgeBase()  # allowed_knowledge_ids defaults to None

    search_kb = AsyncMock(return_value='{"状态": "成功"}')
    monkeypatch.setattr(SearchKnowledgeBase, "search_knowledge", search_kb)

    await tool._arun(query="问题", knowledge_id="287")

    search_kb.assert_awaited_once()


# ---------------------------------------------------------------------------
# Exact KB-id selection must be threaded daily -> task (not collapsed to coarse
# booleans). Regression: a single org KB + single space were injecting ALL 20+
# org KBs because the resolver fell back to ``aget_user_knowledge``.
# ---------------------------------------------------------------------------
def test_to_linsight_submit_threads_exact_kb_ids():
    from bisheng.api.v1.schema.chat_schema import APIChatCompletion, UseKnowledgeBaseParam
    from bisheng.workstation.domain.services.chat_service import _to_linsight_submit

    data = APIChatCompletion(
        clientTimestamp="0",
        model="727",
        text="q",
        task_mode=True,
        use_knowledge_base=UseKnowledgeBaseParam(
            personal_knowledge_enabled=False,
            organization_knowledge_ids=[2745],
            knowledge_space_ids=[3124],
        ),
    )

    submit = _to_linsight_submit(data)

    assert submit.organization_knowledge_ids == [2745]
    assert submit.knowledge_space_ids == [3124]
    assert submit.org_knowledge_enabled is True


async def test_resolve_kbs_uses_exact_ids_not_coarse_all(monkeypatch: pytest.MonkeyPatch):
    """The resolver loads exactly the selected ids and must NOT pull every KB of a
    coarse type via ``aget_user_knowledge`` (the 20+ KB bug)."""
    from types import SimpleNamespace

    from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
    from bisheng.linsight.domain.task_exec import LinsightWorkflowTask

    sv = SimpleNamespace(
        organization_knowledge_ids=[2745],
        knowledge_space_ids=[3124],
        # Booleans are deliberately True to prove they are ignored now.
        org_knowledge_enabled=True,
        personal_knowledge_enabled=True,
        user_id=1,
    )
    by_ids = AsyncMock(return_value=[SimpleNamespace(id=2745), SimpleNamespace(id=3124)])
    all_kbs = AsyncMock(return_value=[SimpleNamespace(id=i) for i in range(20)])
    monkeypatch.setattr(KnowledgeDao, "aget_list_by_ids", by_ids)
    monkeypatch.setattr(KnowledgeDao, "aget_user_knowledge", all_kbs)

    task = LinsightWorkflowTask.__new__(LinsightWorkflowTask)
    result = await task._resolve_user_knowledge_bases(sv)

    assert sorted(kb.id for kb in result) == [2745, 3124]
    by_ids.assert_awaited_once_with([2745, 3124])
    all_kbs.assert_not_awaited()


async def test_resolve_kbs_empty_selection_returns_none(monkeypatch: pytest.MonkeyPatch):
    """No id selection => no KBs (booleans no longer force a coarse fallback)."""
    from types import SimpleNamespace

    from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
    from bisheng.linsight.domain.task_exec import LinsightWorkflowTask

    sv = SimpleNamespace(
        organization_knowledge_ids=None,
        knowledge_space_ids=None,
        org_knowledge_enabled=True,
        personal_knowledge_enabled=True,
        user_id=1,
    )
    all_kbs = AsyncMock(return_value=[SimpleNamespace(id=i) for i in range(20)])
    monkeypatch.setattr(KnowledgeDao, "aget_user_knowledge", all_kbs)

    task = LinsightWorkflowTask.__new__(LinsightWorkflowTask)
    result = await task._resolve_user_knowledge_bases(sv)

    assert result == []
    all_kbs.assert_not_awaited()
