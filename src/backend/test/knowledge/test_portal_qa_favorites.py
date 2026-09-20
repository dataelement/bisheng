"""收藏身份转换和混合检索范围, 外部存储使用内存替身。"""

from datetime import datetime
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from bisheng.knowledge.domain.contracts.retrieval_scope import BackendQueryFilter
from bisheng.knowledge.domain.services.portal_qa_favorites import PortalQaFavorites
from bisheng.knowledge.rag.shared_space_storage import SharedSpaceStorageReader


class Repo:
    def __init__(self, rows):
        self.rows = {row.id: row for row in rows}

    async def find_by_id(self, fid):
        return self.rows.get(fid)

    async def find_by_ids(self, ids):
        return [self.rows[fid] for fid in ids if fid in self.rows]

    async def list_qa_favorite_page(self, *, space_id, after_id, limit):
        return [
            row
            for fid, row in sorted(self.rows.items())
            if fid > after_id and row.knowledge_id == space_id and row.deleted_at is None
        ][:limit]


def fixture():
    favorite = NS(
        id=100,
        tenant_id=7,
        user_id=42,
        knowledge_id=90,
        file_type=1,
        status=2,
        deleted_at=None,
        file_source="favorite_reference",
        user_metadata={"favorite_reference": {"source_space_id": 10, "source_file_id": 1}},
    )
    source = NS(id=1, tenant_id=7, knowledge_id=10, file_type=1, status=2, deleted_at=None, file_source="upload")
    spaces = Repo([NS(id=sid, tenant_id=7, user_id=42, type=3, state=1, is_favorite=sid == 90) for sid in [90, 10, 20]])
    files = Repo([favorite, source])
    durable = NS(resolve=AsyncMock(return_value=NS(entry_file_id=1, content_file_id=201)))
    resolver = PortalQaFavorites(user=NS(user_id=42, tenant_id=7), files=files, spaces=spaces, durable=durable)
    return resolver, favorite, source


async def test_favorite_maps_to_source_entry_and_preserves_physical_resolution():
    resolver, _, _ = fixture()
    binding = await resolver.resolve(90, 100)
    assert (binding.source_space_id, binding.source_file_id) == (10, 1)
    assert (binding.favorite_space_id, binding.favorite_file_id) == (90, 100)
    resolver.durable.resolve.assert_awaited_once_with(
        tenant_id=7,
        requested_space_id=10,
        durable_file_id=1,
        require_view_permission=False,
    )


@pytest.mark.parametrize("case", ["owner", "tenant", "deleted", "source_deleted", "cycle", "wrong_space", "metadata"])
async def test_invalid_favorites_never_produce_source_scope(case):
    resolver, ref, source = fixture()
    if case == "owner":
        resolver.spaces.rows[90].user_id = 9
    elif case == "tenant":
        ref.tenant_id = 8
    elif case == "deleted":
        ref.deleted_at = datetime.now()
    elif case == "source_deleted":
        source.deleted_at = datetime.now()
    elif case == "cycle":
        source.file_source = "favorite_reference"
    elif case == "wrong_space":
        ref.knowledge_id = 89
    else:
        ref.user_metadata = {"favorite_reference": {"source_space_id": "broken"}}
    assert await resolver.resolve(90, 100) is None


async def test_unknown_resolver_failure_propagates():
    resolver, _, _ = fixture()
    resolver.durable.resolve.side_effect = RuntimeError("database unavailable")
    with pytest.raises(RuntimeError, match="database unavailable"):
        await resolver.resolve(90, 100)


async def test_whole_favorite_expands_only_references_and_dedupes():
    resolver, _, _ = fixture()
    whole, refs = await resolver.expand_spaces([90, 20, 90])
    assert whole == (20,)
    assert [(ref.source_space_id, ref.source_file_id) for ref in refs] == [(10, 1)]
    resolver.files.rows.clear()
    assert await resolver.expand_spaces([90]) == ((), ())


def test_mixed_filter_keeps_whole_spaces_or_explicit_documents():
    query = BackendQueryFilter(
        tenant_id=7,
        requested_space_ids=(10, 20),
        routing_version=1,
        canonical_document_ids=(91,),
        canonical_version_ids=(501,),
        whole_space_ids=(20,),
    )
    expr = SharedSpaceStorageReader._full_expr(query)
    assert " or " in expr and "canonical_document_id in [91]" in expr
    clauses = SharedSpaceStorageReader._es_bool_filter(query)
    union = clauses[0]["bool"]
    assert union["minimum_should_match"] == 1
    assert union["should"][0] == {"terms": {"metadata.knowledge_ids": [20]}}
    assert {"terms": {"metadata.canonical_document_id": [91]}} in union["should"][1]["bool"]["filter"]


@pytest.mark.parametrize("direct", [False, True])
async def test_final_check_observes_unfavorite_without_blocking_direct_selection(direct):
    from bisheng.knowledge.domain.contracts.qa_retrieval import QaRetrievalPlan
    from bisheng.knowledge.domain.services.portal_qa_favorites import FavoriteScopeAuthorizer

    resolver, _, source = fixture()
    binding = await resolver.resolve(90, 100)
    plan = QaRetrievalPlan(
        (10,), {10: [1]}, favorite_bindings=(binding,), direct_file_ids_by_space={10: [1]} if direct else {}
    )
    inner = AsyncMock(return_value={1: True})
    inner.context = object()
    assert await FavoriteScopeAuthorizer(inner, resolver, plan)([source]) == {1: True}
    del resolver.files.rows[100]
    assert await FavoriteScopeAuthorizer(inner, resolver, plan)([source]) == {1: direct}


async def test_real_mapping_retains_whole_space_hits_and_excludes_unselected_source_files():
    from dataclasses import replace

    from test.knowledge.test_knowledge_retrieval_scope_resolver import (
        hit,
        make_document,
        make_entry,
        make_resolver,
        make_scope,
    )

    entries = [
        make_entry(1, space_id=10, entry_type="share"),
        make_entry(2, space_id=10, entry_type="share", document_id=92),
        make_entry(3, space_id=20, entry_type="manager", document_id=93),
    ]
    resolver, _, _, _ = make_resolver(entries=entries, documents=[make_document(i) for i in [91, 92, 93]])
    scope = replace(make_scope(explicit={10: (1,)}), whole_space_ids=(20,))
    hits = [hit(document_id=i) for i in [91, 92, 93]]
    mapped = await resolver.map_and_authorize_hits(
        scope, hits, strict_explicit=True, entry_batch_checker=AsyncMock(return_value={1: True, 2: True, 3: True})
    )
    assert {item.entry_file_id for item in mapped} == {1, 3}


async def test_plan_expands_favorite_only_and_preserves_empty_scope(monkeypatch):
    from contextlib import asynccontextmanager

    from bisheng.core import database
    from bisheng.knowledge.domain.services import portal_qa_favorites as module
    from bisheng.knowledge.domain.services.portal_qa_retrieval_service import build_portal_qa_plan

    resolver, _, _ = fixture()

    @asynccontextmanager
    async def session():
        yield object()

    monkeypatch.setattr(database, "get_async_db_session", session)
    monkeypatch.setattr(module, "create_qa_favorites", lambda *args: resolver)
    base = NS(knowledge_scope=None, knowledge_space_ids=[90, 20])
    plan = await build_portal_qa_plan(request=None, user=resolver.user, knowledge_base=base, department_access=None)
    assert plan.space_ids == (10, 20)
    assert plan.whole_space_ids == (20,)
    assert plan.file_ids_by_space == {10: [1]}
    resolver.files.rows.clear()
    base.knowledge_space_ids = [90]
    empty = await build_portal_qa_plan(request=None, user=resolver.user, knowledge_base=base, department_access=None)
    assert empty.space_ids == ()


@pytest.mark.parametrize("selection", ["favorite", "duplicate", "invalid"])
async def test_file_plan_submits_resolved_source_and_dedupes_direct_selection(monkeypatch, selection):
    from contextlib import asynccontextmanager

    from bisheng.core import database
    from bisheng.knowledge.domain.services import knowledge_space_service, portal_qa_favorites
    from bisheng.knowledge.domain.services.portal_qa_retrieval_service import build_portal_qa_plan

    favorites, ref, _ = fixture()

    @asynccontextmanager
    async def session():
        yield object()

    monkeypatch.setattr(database, "get_async_db_session", session)
    monkeypatch.setattr(portal_qa_favorites, "create_qa_favorites", lambda *args: favorites)
    favorites.durable.version_repository = object()
    direct = AsyncMock(return_value={10: [1]} if selection == "duplicate" else {})
    monkeypatch.setattr(
        knowledge_space_service.KnowledgeSpaceService, "resolve_shougang_portal_qa_scope_file_ids", direct
    )
    refs = [NS(knowledge_space_id=90, file_id=100)]
    if selection == "duplicate":
        refs.append(NS(knowledge_space_id=10, file_id=1))
    elif selection == "invalid":
        ref.deleted_at = datetime.now()
    scope = NS(mode="files", file_refs=refs, folder_refs=[])
    plan = await build_portal_qa_plan(
        request=None,
        user=favorites.user,
        department_access=None,
        knowledge_base=NS(knowledge_scope=scope, knowledge_space_ids=[90, 10]),
    )
    assert plan.file_ids_by_space == ({} if selection == "invalid" else {10: [1]})
    assert plan.space_ids == (() if selection == "invalid" else (10,))
    assert [item.file_id for item in direct.await_args.kwargs["file_refs"]] == ([1] if selection == "duplicate" else [])


async def test_favorite_tree_pages_keep_logical_ids_and_disable_invalid_sources(monkeypatch):
    from contextlib import asynccontextmanager
    from copy import deepcopy

    from bisheng.knowledge.domain.services import knowledge_space_service as module
    from bisheng.knowledge.domain.services import portal_qa_favorites

    resolver, ref, _ = fixture()
    ref.file_name = "有效收藏.pdf"
    invalid = deepcopy(ref)
    invalid.id, invalid.file_name = 101, "失效收藏.pdf"
    invalid.user_metadata = {}
    resolver.files.rows[101] = invalid

    @asynccontextmanager
    async def session():
        yield object()

    monkeypatch.setattr(module, "get_async_db_session", session)
    monkeypatch.setattr(portal_qa_favorites, "create_qa_favorites", lambda *args: resolver)
    service = module.KnowledgeSpaceService(None, resolver.user)
    service._filter_visible_child_items = AsyncMock(side_effect=lambda files, **kw: files)
    service._get_valid_department_space_ids = AsyncMock(return_value=set())
    first = await service.list_qa_favorite_children(space_id=90, parent_id=None, cursor=None, page_size=1)
    assert first["data"][0]["id"] == 100 and first["data"][0]["selectable"]
    second = await service.list_qa_favorite_children(
        space_id=90, parent_id=None, cursor=first["next_cursor"], page_size=1
    )
    assert second["data"][0]["id"] == 101 and not second["data"][0]["selectable"]
    assert not second["has_more"]
    resolver.spaces.rows[90].user_id = 8
    from bisheng.common.errcode.knowledge_space import SpacePermissionDeniedError

    with pytest.raises(SpacePermissionDeniedError):
        await service.list_qa_favorite_children(space_id=90, parent_id=None, cursor=None, page_size=1)


@pytest.mark.parametrize("kind", [None, "publish", "share"])
async def test_real_document_resolver_maps_favorite_to_current_physical_content(kind):
    from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
    from bisheng.knowledge.domain.services.knowledge_document_entry_resolver import (
        KnowledgeDocumentDurableReferenceResolver,
        KnowledgeDocumentEntryResolver,
    )
    from test.knowledge.test_knowledge_retrieval_scope_resolver import make_document, make_entry

    resolver, _, _ = fixture()
    source = make_entry(1, space_id=10, entry_type=kind, document_id=91 if kind else None)
    source.status = 2
    resolver.files.rows[1] = source
    content_id = 201 if kind else 1
    if kind:
        manager = make_entry(201, space_id=20, entry_type="manager")
        manager.status = 2
        resolver.files.rows[201] = manager
    docs = Repo([make_document(space_id=20 if kind else 10)])
    versions = Repo(
        [KnowledgeDocumentVersion(id=501, document_id=91, knowledge_file_id=content_id, version_no=1, tenant_id=7)]
    )
    versions.find_by_knowledge_file_id = AsyncMock(return_value=None if kind else versions.rows[501])
    entry = KnowledgeDocumentEntryResolver(
        document_repository=docs,
        version_repository=versions,
        file_repository=resolver.files,
        permission_loader=AsyncMock(return_value=set()),
    )
    resolver.durable = KnowledgeDocumentDurableReferenceResolver(
        entry_resolver=entry,
        version_repository=versions,
        file_repository=resolver.files,
    )
    binding = await resolver.resolve(90, 100)
    assert binding.source_file_id == 1
    resolved = await resolver.durable.resolve(
        tenant_id=7, requested_space_id=10, durable_file_id=binding.source_file_id, require_view_permission=False
    )
    assert resolved.content_file_id == content_id
    if kind:
        assert resolved.canonical_version_id == 501


async def test_favorite_repository_pages_and_category_counts_exclude_references(async_db_session):
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
    from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
        KnowledgeFileRepositoryImpl,
    )

    rows = [
        KnowledgeFile(
            id=fid,
            knowledge_id=sid,
            tenant_id=1,
            file_name=f"{fid}.pdf",
            file_type=1,
            status=2,
            file_source=source,
            file_encoding="SG-ZC-A-001",
            deleted_at=deleted,
        )
        for fid, sid, source, deleted in [
            (1, 90, "favorite_reference", None),
            (2, 90, "favorite_reference", None),
            (3, 90, "favorite_reference", datetime.now()),
            (4, 90, "upload", None),
            (5, 91, "favorite_reference", None),
        ]
    ]
    async_db_session.add_all(rows)
    await async_db_session.commit()
    repo = KnowledgeFileRepositoryImpl(async_db_session)
    first = await repo.list_qa_favorite_page(space_id=90, after_id=0, limit=1)
    second = await repo.list_qa_favorite_page(space_id=90, after_id=first[0].id, limit=2)
    assert [row.id for row in first + second] == [1, 2]
    categories = await repo.list_qa_category_candidates(
        space_ids=[90, 91], document_type="ZC", file_subcategory_code=None, before_id=None, limit=None
    )
    assert [row.id for row in categories] == [4]
