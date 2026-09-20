"""门户统一召回的数量、排序和故障边界。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.knowledge.domain.contracts.retrieval_scope import CanonicalChunkHit
from bisheng.knowledge.domain.services.portal_qa_retrieval_service import (
    UnifiedSharedRetriever,
)


def hit(doc, chunk=0):
    return CanonicalChunkHit(doc, doc, chunk, 1.0, text=str(doc), content_generation=1, membership_generation=1)


def engine(dense, sparse, *, authorize=None, target=3):
    resolver = SimpleNamespace(
        build_backend_filter=lambda scope, **kwargs: scope,
        map_and_authorize_hits=AsyncMock(side_effect=authorize or (lambda scope, hits, **kwargs: hits)),
    )

    class Cursor:
        def __init__(self, search):
            self.search = search
            self.offset = 0
            self.closed = False

        async def next_batch(self):
            rows = await self.search(limit=2, offset=self.offset)
            self.offset += len(rows)
            return rows

        async def close(self):
            self.closed = True

    dense_search, sparse_search = AsyncMock(side_effect=dense), AsyncMock(side_effect=sparse)
    cursors = [Cursor(dense_search), Cursor(sparse_search)]
    reader = SimpleNamespace(
        open_milvus_cursor=AsyncMock(return_value=cursors[0]),
        open_es_cursor=AsyncMock(return_value=cursors[1]),
        search_milvus=dense_search,
        search_es=sparse_search,
        cursors=cursors,
    )
    return UnifiedSharedRetriever(
        resolver=resolver,
        reader=reader,
        candidate_limit=target,
        initial_limit=2,
        max_rounds=3,
        pool_limit=16,
        search_timeout=1,
        batch_authorizer=AsyncMock(),
    ), reader


@pytest.mark.parametrize("spaces", [tuple(range(1, 2)), tuple(range(1, 21)), tuple(range(1, 242))])
async def test_unified_membership_does_not_fan_out_by_space(spaces):
    e, r = engine(lambda **kw: [hit(1), hit(2)], lambda **kw: [hit(2), hit(3)])
    scope = SimpleNamespace(requested_space_ids=spaces)
    result = await e.retrieve(scope=scope, query="q", vector=[0.1])
    assert [h.canonical_document_id for h in result.hits] == [2, 1, 3]
    assert r.search_es.await_count == r.search_milvus.await_count == 1
    assert r.open_es_cursor.await_args.kwargs["filter_"] is scope
    assert all(c.closed for c in r.cursors)


async def test_denied_first_page_refills_and_marks_exhaustion():
    def authorize(scope, hits, **kw):
        return [h for h in hits if h.canonical_document_id >= 3]

    def search(**kw):
        return [hit(i) for i in range(1, 5)][kw["offset"] : kw["offset"] + kw["limit"]]

    e, r = engine(search, lambda **kw: [], authorize=authorize)
    result = await e.retrieve(scope=object(), query="q", vector=[0.1])
    assert [h.canonical_document_id for h in result.hits] == [3, 4]
    assert [c.kwargs["limit"] for c in r.search_milvus.await_args_list] == [2, 2, 2]
    assert [c.kwargs["offset"] for c in r.search_milvus.await_args_list] == [0, 2, 4]
    assert result.scope_complete


async def test_both_backends_fail_without_claiming_empty():
    e, _ = engine(RuntimeError("dense down"), RuntimeError("sparse down"))
    with pytest.raises(Exception, match="retrieval backends unavailable"):
        await e.retrieve(scope=object(), query="q", vector=[0.1])


async def test_one_backend_failure_preserves_authorized_results_as_degraded():
    e, _ = engine(RuntimeError("dense down"), lambda **kw: [hit(9)], target=1)
    result = await e.retrieve(scope=object(), query="q", vector=None)
    assert result.hits[0].canonical_document_id == 9
    assert result.degraded_reasons and not result.scope_complete


async def test_authorization_failure_does_not_degrade_to_unchecked_content():
    async def broken(*args, **kw):
        raise RuntimeError("permission unavailable")

    e, _ = engine(lambda **kw: [hit(1)], lambda **kw: [], authorize=broken)
    with pytest.raises(RuntimeError, match="permission unavailable"):
        await e.retrieve(scope=object(), query="q", vector=[0.1])


async def test_final_revocation_refills_from_next_batch_and_rechecks_survivors():
    def search(**kw):
        return [hit(i) for i in range(1, 5)][kw["offset"] : kw["offset"] + kw["limit"]]

    e, r = engine(search, lambda **kw: [], target=2)
    finalized = []

    async def finalize(result):
        finalized.append([h.canonical_document_id for h in result.hits])
        return {(1, 1, 0)} if len(finalized) == 1 else set()

    result = await e.retrieve(scope=object(), query="q", vector=[0.1], finalize=finalize)
    assert finalized == [[1, 2], [2, 3]]
    assert [h.canonical_document_id for h in result.hits] == [2, 3]
    assert result.scope_complete
    assert all(cursor.closed for cursor in r.cursors)


async def test_cross_page_rank_contribution_does_not_repeat_authorization():
    e, r = engine(
        lambda **kw: [hit(1), hit(2)] if kw["offset"] == 0 else [],
        lambda **kw: [hit(3), hit(4)] if kw["offset"] == 0 else [hit(1)],
        target=5,
    )
    result = await e.retrieve(scope=object(), query="q", vector=[0.1])
    assert result.hits[0].canonical_document_id == 1
    calls = e.resolver.map_and_authorize_hits.await_args_list
    assert sum(len(call.args[1]) for call in calls) == 4
    assert not result.scope_complete  # 稀疏路的重复页面被识别为无进展。


async def test_duplicate_page_does_not_hide_valid_later_candidates():
    pages = iter([[hit(1), hit(1)], [hit(1), hit(1)], [hit(2), hit(3)]])
    e, _ = engine(lambda **kw: next(pages), lambda **kw: [], target=3)
    result = await e.retrieve(scope=object(), query="q", vector=[0.1])
    assert [item.canonical_document_id for item in result.hits] == [1, 2, 3]
    assert result.scope_complete


async def test_final_revocation_uses_buffer_before_requesting_another_batch():
    e, r = engine(lambda **kw: [hit(1), hit(2)], lambda **kw: [], target=1)

    async def finalize(result):
        return {(1, 1, 0)} if result.hits[0].canonical_document_id == 1 else set()

    result = await e.retrieve(scope=object(), query="q", vector=[0.1], finalize=finalize)
    assert result.hits[0].canonical_document_id == 2
    assert r.search_milvus.await_count == 1


@pytest.mark.parametrize("ids", [[], [1], list(range(1, 242))])
async def test_whole_space_plan_does_not_expand_files(monkeypatch, ids):
    from bisheng.knowledge.domain.services.portal_qa_retrieval_service import build_portal_qa_plan
    from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

    from contextlib import asynccontextmanager
    from bisheng.core import database
    from bisheng.knowledge.domain.services import portal_qa_favorites
    from test.knowledge.test_portal_qa_favorites import Repo, PortalQaFavorites

    @asynccontextmanager
    async def session():
        yield object()

    spaces = Repo([SimpleNamespace(id=sid, is_favorite=False) for sid in ids])
    favorites = PortalQaFavorites(user=None, spaces=spaces, files=Repo([]), durable=None)
    monkeypatch.setattr(database, "get_async_db_session", session)
    monkeypatch.setattr(portal_qa_favorites, "create_qa_favorites", lambda *args: favorites)
    expand = AsyncMock(side_effect=AssertionError("must not enumerate files"))
    monkeypatch.setattr(KnowledgeSpaceService, "resolve_shougang_portal_qa_scope_file_ids", expand)
    plan = await build_portal_qa_plan(
        request=None,
        user=None,
        department_access=None,
        knowledge_base=SimpleNamespace(knowledge_scope=None, knowledge_space_ids=ids),
    )
    assert plan.space_ids == tuple(ids)
    assert plan.file_ids_by_space is None
    expand.assert_not_called()


async def test_entry_authorization_is_cached_only_within_same_user_phase():
    from bisheng.knowledge.domain.services.portal_qa_retrieval_service import PortalEntryAuthorizer
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileStatus

    entry = SimpleNamespace(id=1, knowledge_id=10, status=KnowledgeFileStatus.SUCCESS.value)
    first = SimpleNamespace(
        login_user=SimpleNamespace(user_id=1),
        department_file_view_access_service=SimpleNamespace(
            evaluate_files=AsyncMock(return_value={1: SimpleNamespace(status="not_applicable")})
        ),
        _require_file_view_permission=AsyncMock(),
    )
    first_authorizer = PortalEntryAuthorizer(first)
    assert await first_authorizer([entry]) == {1: True}
    assert await first_authorizer([entry]) == {1: True}
    first._require_file_view_permission.assert_awaited_once_with(10, 1)
    second = SimpleNamespace(
        login_user=SimpleNamespace(user_id=2),
        department_file_view_access_service=SimpleNamespace(
            evaluate_files=AsyncMock(return_value={1: SimpleNamespace(status="approval_required")})
        ),
        _require_file_view_permission=AsyncMock(),
    )
    assert await PortalEntryAuthorizer(second)([entry]) == {1: False}
    second._require_file_view_permission.assert_not_called()


@pytest.mark.parametrize("level,tenant,expected", [("public", 7, True), ("public", 8, False), ("team", 7, False)])
async def test_public_entry_is_authoritative_and_other_entries_still_require_access(level, tenant, expected):
    from bisheng.knowledge.domain.services.portal_qa_retrieval_service import PortalEntryAuthorizer
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileStatus

    entry = SimpleNamespace(id=1, knowledge_id=10, tenant_id=7, status=KnowledgeFileStatus.SUCCESS.value)
    access = AsyncMock(return_value={1: SimpleNamespace(status="approval_required")})
    owner = SimpleNamespace(
        login_user=SimpleNamespace(user_id=1, tenant_id=7),
        department_file_view_access_service=SimpleNamespace(evaluate_files=access),
    )
    repository = SimpleNamespace(
        find_qa_spaces_by_ids=AsyncMock(return_value=[(SimpleNamespace(id=10, tenant_id=tenant), level)])
    )
    authorizer = PortalEntryAuthorizer(owner, space_repository=repository)
    assert await authorizer([entry]) == {1: expected}
    if level == "public":
        access.assert_not_called()
