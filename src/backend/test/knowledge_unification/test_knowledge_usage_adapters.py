"""AC-35/36/37/66/68/79/82/83: legacy knowledge consumers use visibility.

Exercise the actual list and RAG consumer; isolate only actor/FGA/DAO ports.
Successful primary-version filtering remains the existing retrieval contract.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.services.knowledge_permission_service import KnowledgePermissionService
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from test.knowledge import test_knowledge_list_visible_first as fixtures


async def test_rag_uses_visible_candidates_without_a_use_result_key(monkeypatch):
    check = AsyncMock(return_value={100: {"visible"}, 101: set()})
    monkeypatch.setattr(KnowledgePermissionService, "get_knowledge_action_map_async", check)
    user = object()
    assert await KnowledgeRag.afilter_usable_knowledge_ids(user, [100, 101]) == {100}
    check.assert_awaited_once_with(user, [100, 101], ["visible"])


async def test_rag_without_identity_never_checks_or_reads_candidates(monkeypatch):
    check = AsyncMock(side_effect=AssertionError("no anonymous permission query"))
    monkeypatch.setattr(KnowledgePermissionService, "get_knowledge_action_map_async", check)
    assert await KnowledgeRag.afilter_usable_knowledge_ids(None, [100]) == set()
    check.assert_not_awaited()


@pytest.mark.parametrize("action", ["use", "visible"])
async def test_legacy_use_list_returns_the_same_visible_page_without_action_rematerialization(monkeypatch, action):
    module = fixtures.ks_mod
    fixtures._stub_enrichment(monkeypatch)
    runtime = SimpleNamespace(list_visible_objects=AsyncMock(return_value=fixtures._visible("100", "101")))
    monkeypatch.setattr(module, "get_f048_runtime", AsyncMock(return_value=runtime))
    monkeypatch.setattr(module, "resolve_permission_actor", AsyncMock(return_value=fixtures._actor()))
    rows = AsyncMock(return_value=[fixtures._knowledge(100), fixtures._knowledge(101)])
    monkeypatch.setattr(module.KnowledgeDao, "aget_all_knowledge", rows)
    check = AsyncMock(side_effect=AssertionError("visible is already proven by enumeration"))
    monkeypatch.setattr(KnowledgeService.permission_service, "get_knowledge_action_map_async", check)
    page = await KnowledgeService.get_knowledge(
        request=None,
        login_user=fixtures._User(),
        knowledge_type=fixtures.KnowledgeTypeEnum.NORMAL,
        page_size=10,
        action=action,
    )
    assert [item.id for item in page.data] == [100, 101]
    assert all(item.actions == ["visible"] for item in page.data)
    assert rows.await_args.kwargs["id_in"] == [100, 101]
    check.assert_not_awaited()
