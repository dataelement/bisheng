from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from langchain_core.documents import Document

from bisheng.citation.domain.schemas.citation_schema import (
    CitationRegistryItemSchema,
    CitationType,
    RagCitationItemSchema,
    RagCitationPayloadSchema,
)
from bisheng.citation.domain.services.citation_resolve_service import (
    CitationResolveService,
)
from bisheng.common.errcode.http_error import NotFoundError
from bisheng.core.context.tenant import set_current_tenant_id
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)
from bisheng.knowledge.domain.services.knowledge_file_visibility_service import (
    KnowledgeFileVisibilityService,
)
from bisheng.knowledge.domain.services.knowledge_space_chat_service import (
    KnowledgeSpaceChatService,
)
from bisheng.knowledge.domain.services.knowledge_space_service import (
    KnowledgeSpaceService,
)

_VISIBILITY_MODULE = "bisheng.knowledge.domain.services.knowledge_file_visibility_service"


def _login_user(*, user_id: int = 7, tenant_id: int = 42, is_admin: bool = False):
    user = MagicMock()
    user.user_id = user_id
    user.user_name = f"user-{user_id}"
    user.tenant_id = tenant_id
    user.is_admin = MagicMock(return_value=is_admin)
    return user


def _rag(citation_id: str, document_id: int, *, access_scope: str = "per_user"):
    return CitationRegistryItemSchema(
        citationId=citation_id,
        type=CitationType.RAG,
        accessScope=access_scope,
        sourcePayload=RagCitationPayloadSchema(
            knowledgeId=8,
            documentId=document_id,
            documentName=f"secret-{document_id}.pdf",
            snippet="must-not-leak",
        ),
    )


async def test_admin_index_prefilter_still_excludes_unpublished_and_delete_residue():
    set_current_tenant_id(42)
    service = KnowledgeFileVisibilityService(request=MagicMock(), login_user=_login_user(is_admin=True))
    service._list_primary_file_ids_in_space = AsyncMock(return_value={101, 102, 103})
    service._count_primary_files_in_space = AsyncMock(return_value=3)
    service._list_file_change_excluded_ids = AsyncMock(return_value={101, 102})
    service._non_primary_ids = AsyncMock(return_value=set())

    # F048 has no admin short-circuit: an administrator resolves ``visible``
    # through the same action check as everyone else (identity relations in
    # OpenFGA carry the privilege), so the file-change exclusion is what must
    # still keep 101/102 out of the index.
    with patch(
        f"{_VISIBILITY_MODULE}.batch_check_business_actions",
        AsyncMock(return_value={"103": frozenset({"visible"})}),
    ):
        result = await service.build_index_prefilter(space_id=8, candidate_file_ids=None)

    # F048 pushes down the positive list when it is the smaller side; either
    # shape is fine as long as the unpublished / delete-residue files cannot
    # come back from the index.
    assert result.strategy == "in"
    assert result.milvus_expr == "document_id in [103]"
    assert result.es_filter == [{"terms": {"metadata.document_id": [103]}}]


async def test_file_change_exclusions_use_one_explicit_tenant_scoped_query_per_guard():
    set_current_tenant_id(42)
    service = KnowledgeFileVisibilityService(request=MagicMock(), login_user=_login_user())
    publication_guard = MagicMock()
    publication_guard.list_unpublished_ids = AsyncMock(return_value={101})
    deletion_guard = MagicMock()
    deletion_guard.list_deleted_ids = AsyncMock(return_value={102})
    mutation_projection = MagicMock()
    mutation_projection.list_invisible_ids = AsyncMock(return_value={103})
    service._knowledge_space_file_publication_guard = publication_guard
    service._knowledge_space_deletion_guard = deletion_guard
    service._knowledge_space_mutation_read_projection = mutation_projection

    assert await service._list_file_change_excluded_ids(space_ids=[8, 9]) == {101, 102, 103}
    publication_guard.list_unpublished_ids.assert_awaited_once_with(
        tenant_id=42,
        space_ids=[8, 9],
    )
    deletion_guard.list_deleted_ids.assert_awaited_once_with(
        tenant_id=42,
        space_ids=[8, 9],
    )
    mutation_projection.list_invisible_ids.assert_awaited_once_with(
        tenant_id=42,
        space_ids=[8, 9],
    )


async def test_old_view_projects_preinstalled_rename_metadata_and_chunk_text():
    set_current_tenant_id(42)
    service = KnowledgeFileVisibilityService(request=MagicMock(), login_user=_login_user())
    projection = MagicMock()
    projection.name_projection = AsyncMock(return_value={101: ("old.pdf", "new.pdf")})
    service._knowledge_space_mutation_read_projection = projection
    documents = [
        Document(
            page_content="document_name: new.pdf\nbody",
            metadata={"document_id": 101, "document_name": "new.pdf"},
        )
    ]

    result = await service.project_mutation_retrieval_names(space_id=8, documents=documents)

    assert result[0].metadata["document_name"] == "old.pdf"
    assert "new.pdf" not in result[0].page_content
    assert "old.pdf" in result[0].page_content

    projection.name_projection.return_value = {101: ("new.pdf", "old.pdf")}
    new_view = [
        Document(
            page_content="document_name: old.pdf\nbody",
            metadata={"document_id": 101, "document_name": "old.pdf"},
        )
    ]
    result = await service.project_mutation_retrieval_names(space_id=8, documents=new_view)
    assert result[0].metadata["document_name"] == "new.pdf"
    assert "old.pdf" not in result[0].page_content


async def test_transition_authorization_uses_old_space_then_reverses_on_new_view():
    set_current_tenant_id(42)
    old_user = KnowledgeFileVisibilityService(request=MagicMock(), login_user=_login_user(user_id=7))
    new_user = KnowledgeFileVisibilityService(request=MagicMock(), login_user=_login_user(user_id=8))
    for service in (old_user, new_user):
        service._list_file_change_excluded_ids = AsyncMock(return_value=set())
        projection = MagicMock()
        projection.authoritative_space_ids = AsyncMock(return_value={101: 8})
        service._knowledge_space_mutation_read_projection = projection
    old_user.is_space_visible = AsyncMock(side_effect=lambda space_id: space_id == 8)
    new_user.is_space_visible = AsyncMock(side_effect=lambda space_id: space_id == 9)

    assert await old_user.filter_file_change_visible_ids(space_ids=[8], resource_ids=[101]) == {101}
    assert await new_user.filter_file_change_visible_ids(space_ids=[8], resource_ids=[101]) == set()

    old_user._knowledge_space_mutation_read_projection.authoritative_space_ids.return_value = {101: 9}
    new_user._knowledge_space_mutation_read_projection.authoritative_space_ids.return_value = {101: 9}
    assert await old_user.filter_file_change_visible_ids(space_ids=[9], resource_ids=[101]) == set()
    assert await new_user.filter_file_change_visible_ids(space_ids=[9], resource_ids=[101]) == {101}


async def test_citation_old_view_projects_document_name_snippet_and_child_content():
    set_current_tenant_id(42)
    item = _rag("renamed", 101)
    payload = item.sourcePayload.model_copy(
        update={
            "documentName": "new.pdf",
            "snippet": "match in new.pdf",
            "items": [
                RagCitationItemSchema(itemId="chunk-1", content="content from new.pdf")
            ],
        }
    )
    item = item.model_copy(update={"sourcePayload": payload})
    service = CitationResolveService(MagicMock())
    visibility = MagicMock()
    visibility.old_name_projection = AsyncMock(return_value={101: ("old.pdf", "new.pdf")})
    service._build_visibility_service = MagicMock(return_value=visibility)

    projected = await service._project_old_file_names([item], _login_user())

    projected_payload = projected[0].sourcePayload
    assert projected_payload.documentName == "old.pdf"
    assert projected_payload.snippet == "match in old.pdf"
    assert projected_payload.items[0].content == "content from old.pdf"


async def test_file_change_guard_rejects_root_tenant_fallback_on_context_mismatch():
    set_current_tenant_id(1)
    service = KnowledgeFileVisibilityService(request=MagicMock(), login_user=_login_user(tenant_id=42))

    with pytest.raises(RuntimeError, match="matching tenant context"):
        await service.filter_file_change_visible_ids(space_ids=[8], resource_ids=[101])

    set_current_tenant_id(42)


async def test_post_filter_runs_rebac_before_file_change_hard_deny():
    set_current_tenant_id(42)
    service = KnowledgeFileVisibilityService(request=MagicMock(), login_user=_login_user())
    order: list[str] = []

    async def rebac_filter(space_id, file_ids):
        assert space_id == 8
        assert set(file_ids) == {101, 102, 103}
        order.append("rebac")
        return {101, 102}

    async def file_change_filter(*, space_ids, resource_ids):
        assert space_ids == [8]
        assert set(resource_ids) == {101, 102}
        order.append("file-change")
        return {102}

    service.post_filter_rebac_visible_files = rebac_filter
    service.filter_file_change_visible_ids = file_change_filter

    visible = await service.post_filter_visible_files(8, {101, 102, 103})

    assert visible == {102}
    assert order == ["rebac", "file-change"]


async def test_single_file_rag_checks_rebac_before_publication_and_deletion_guards():
    set_current_tenant_id(42)
    service = KnowledgeSpaceChatService(request=MagicMock(), login_user=_login_user())
    order: list[str] = []
    file_record = MagicMock(id=101, knowledge_id=8)
    permission_service = MagicMock()

    # F048 resolves the relation and the action in one call.
    async def require_file_action(*args, **kwargs):
        assert args == (101, "visible")
        assert kwargs == {"space_id": 8}
        order.append("rebac")
        return file_record

    permission_service._require_file_action = require_file_action
    service._knowledge_space_permission_service = permission_service
    visibility = MagicMock()

    async def require_file_change_visible(**kwargs):
        assert kwargs == {"space_id": 8, "resource_id": 101}
        order.append("file-change")

    visibility.require_file_change_visible = require_file_change_visible
    service._knowledge_file_visibility_service = visibility

    assert await service._require_file_view_permission(8, 101) is file_record
    assert order == ["rebac", "file-change"]


async def test_shared_citation_is_dropped_before_enrichment_when_f046_hides_file():
    set_current_tenant_id(42)
    service = CitationResolveService(MagicMock())
    service.runtime_cache_service.get_citations_by_ids = AsyncMock(return_value=[_rag("hidden", 101, access_scope="shared")])
    service._permitted_file_ids = AsyncMock(return_value=set())
    service._file_change_visible_ids = AsyncMock(return_value=set())
    service._canonicalize_rag_items = AsyncMock(side_effect=lambda items, _user: list(items))
    service._project_old_file_names = AsyncMock(side_effect=lambda items, _user: list(items))
    service._enrich_item = AsyncMock(side_effect=AssertionError("hidden citation must not be enriched"))

    result = await service.resolve_citations(["hidden"], _login_user())

    assert result == []
    service._file_change_visible_ids.assert_awaited_once()
    service._enrich_item.assert_not_awaited()


async def test_shared_citation_keeps_existing_access_scope_semantics_when_not_f046_hidden():
    set_current_tenant_id(42)
    item = _rag("shared", 101, access_scope="shared")
    service = CitationResolveService(MagicMock())
    service.runtime_cache_service.get_citations_by_ids = AsyncMock(return_value=[item])
    service._permitted_file_ids = AsyncMock(return_value=set())
    service._file_change_visible_ids = AsyncMock(return_value={101})
    service._canonicalize_rag_items = AsyncMock(side_effect=lambda items, _user: list(items))
    service._project_old_file_names = AsyncMock(return_value=[item])
    service._enrich_item = AsyncMock(return_value=item)

    result = await service.resolve_citations(["shared"], _login_user())

    assert [one.citationId for one in result] == ["shared"]
    service._enrich_item.assert_awaited_once_with(item, service._enrich_item.await_args.args[1], url_allowed=False)


async def test_citation_f046_filter_batches_all_spaces_without_per_file_queries():
    set_current_tenant_id(42)
    service = CitationResolveService(MagicMock())
    items = [_rag("a", 101), _rag("b", 102)]
    items[1] = items[1].model_copy(
        update={
            "sourcePayload": items[1].sourcePayload.model_copy(update={"knowledgeId": 9})
        }
    )
    visibility = MagicMock()
    visibility.filter_file_change_visible_ids = AsyncMock(return_value={101, 102})
    service._build_visibility_service = MagicMock(return_value=visibility)

    visible = await service._file_change_visible_ids(items, _login_user())

    assert visible == {101, 102}
    assert visibility.filter_file_change_visible_ids.await_args_list == [
        call(space_ids=[8, 9], resource_ids=[101, 102])
    ]


async def test_uncanonicalized_citation_missing_space_metadata_fails_closed():
    service = CitationResolveService(MagicMock())
    items = [_rag("a", 101), _rag("b", 102)]
    items = [
        item.model_copy(
            update={
                "sourcePayload": item.sourcePayload.model_copy(update={"knowledgeId": None})
            }
        )
        for item in items
    ]
    grouped = await service._resolve_rag_space_pairs(items)

    assert grouped == {0: {101, 102}}


async def test_citation_file_batch_repository_encodes_explicit_tenant_in_sql():
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)

    await KnowledgeFileRepositoryImpl(session).find_by_ids_for_tenant(
        tenant_id=42,
        entity_ids=[101, 102],
    )

    statement = session.execute.await_args.args[0]
    compiled = statement.compile()
    assert "knowledgefile.tenant_id" in str(compiled)
    assert 42 in compiled.params.values()
    assert [101, 102] in compiled.params.values()


async def test_cross_space_citation_uses_current_space_permissions_after_projection_cleanup():
    set_current_tenant_id(42)
    item = _rag("moved", 101)
    file_row = MagicMock(
        id=101,
        tenant_id=42,
        knowledge_id=9,
        file_name="secret-101.pdf",
    )

    order: list[str] = []

    def visibility_for(user_id: int):
        visibility = MagicMock()
        visibility.require_explicit_tenant = MagicMock(return_value=42)

        async def authoritative_space_ids(**_kwargs):
            order.append(f"canonical:{user_id}")
            return {}

        visibility.authoritative_mutation_space_ids = AsyncMock(side_effect=authoritative_space_ids)

        async def rebac(space_id, file_ids):
            order.append(f"permission:{user_id}")
            allowed_space = 8 if user_id == 7 else 9
            return set(file_ids) if int(space_id) == allowed_space else set()

        visibility.post_filter_rebac_visible_files = AsyncMock(side_effect=rebac)
        visibility.filter_file_change_visible_ids = AsyncMock(return_value={101})
        visibility.old_name_projection = AsyncMock(return_value={})
        return visibility

    file_repository = MagicMock()
    file_repository.find_by_ids_for_tenant = AsyncMock(return_value=[file_row])
    old_viewer_service = CitationResolveService(
        MagicMock(),
        knowledge_file_repository=file_repository,
    )
    old_viewer_service.runtime_cache_service.get_citation = AsyncMock(return_value=item)
    old_viewer_service._build_visibility_service = MagicMock(return_value=visibility_for(7))
    target_viewer_service = CitationResolveService(
        MagicMock(),
        knowledge_file_repository=file_repository,
    )
    target_viewer_service.runtime_cache_service.get_citation = AsyncMock(return_value=item)
    target_viewer_service._build_visibility_service = MagicMock(return_value=visibility_for(8))

    with (
        patch(
            "bisheng.citation.domain.services.citation_resolve_service.KnowledgeFileDao.query_by_id_sync",
            return_value=file_row,
        ),
        patch(
            "bisheng.citation.domain.services.citation_resolve_service.KnowledgeService.get_file_share_url",
            side_effect=lambda *_args: (order.append("url"), ("download", "preview"))[1],
        ) as share_url,
    ):
        with pytest.raises(NotFoundError):
            await old_viewer_service.resolve_citation("moved", _login_user(user_id=7))
        share_url.assert_not_called()

        resolved = await target_viewer_service.resolve_citation("moved", _login_user(user_id=8))

    assert resolved.sourcePayload.knowledgeId == 9
    assert resolved.sourcePayload.downloadUrl == "download"
    assert resolved.sourcePayload.previewUrl == "preview"
    assert file_repository.find_by_ids_for_tenant.await_count == 2
    assert all(
        one.kwargs == {"tenant_id": 42, "entity_ids": [101]}
        for one in file_repository.find_by_ids_for_tenant.await_args_list
    )
    assert order == ["canonical:7", "permission:7", "canonical:8", "permission:8", "url"]
    share_url.assert_called_once()


async def test_active_old_view_citation_keeps_source_space_permission_and_name():
    set_current_tenant_id(42)
    item = _rag("moving", 101).model_copy(
        update={
            "sourcePayload": _rag("moving", 101).sourcePayload.model_copy(
                update={"documentName": "new.pdf", "snippet": "from new.pdf"}
            )
        }
    )
    file_row = MagicMock(id=101, tenant_id=42, knowledge_id=9, file_name="new.pdf")
    file_repository = MagicMock()
    file_repository.find_by_ids_for_tenant = AsyncMock(return_value=[file_row])
    visibility = MagicMock()
    visibility.require_explicit_tenant = MagicMock(return_value=42)
    visibility.authoritative_mutation_space_ids = AsyncMock(return_value={101: 8})
    visibility.old_name_projection = AsyncMock(return_value={101: ("old.pdf", "new.pdf")})
    visibility.post_filter_rebac_visible_files = AsyncMock(return_value={101})
    visibility.filter_file_change_visible_ids = AsyncMock(return_value={101})

    service = CitationResolveService(
        MagicMock(),
        knowledge_file_repository=file_repository,
    )
    service.runtime_cache_service.get_citation = AsyncMock(return_value=item)
    service._build_visibility_service = MagicMock(return_value=visibility)

    with (
        patch(
            "bisheng.citation.domain.services.citation_resolve_service.KnowledgeFileDao.query_by_id_sync",
            return_value=file_row,
        ),
        patch(
            "bisheng.citation.domain.services.citation_resolve_service.KnowledgeService.get_file_share_url",
            return_value=("download", "preview"),
        ),
    ):
        resolved = await service.resolve_citation("moving", _login_user())

    assert resolved.sourcePayload.knowledgeId == 8
    assert resolved.sourcePayload.documentName == "old.pdf"
    assert resolved.sourcePayload.snippet == "from old.pdf"
    visibility.authoritative_mutation_space_ids.assert_awaited_once_with(
        space_ids=[8, 9],
        resource_ids=[101],
    )
    visibility.post_filter_rebac_visible_files.assert_awaited_once_with(8, {101})


async def test_batch_citations_authoritatively_refresh_space_and_name_without_per_file_queries():
    set_current_tenant_id(42)
    items = [_rag("a", 101), _rag("b", 102)]
    items[0] = items[0].model_copy(
        update={
            "sourcePayload": items[0].sourcePayload.model_copy(
                update={
                    "documentName": "old-a.pdf",
                    "snippet": "from old-a.pdf",
                    "items": [RagCitationItemSchema(itemId="chunk-a", content="old-a.pdf body")],
                }
            )
        }
    )
    items[1] = items[1].model_copy(
        update={
            "sourcePayload": items[1].sourcePayload.model_copy(
                update={
                    "documentName": "old-b.pdf",
                    "snippet": "from old-b.pdf",
                    "items": [RagCitationItemSchema(itemId="chunk-b", content="old-b.pdf body")],
                }
            )
        }
    )
    file_rows = [
        MagicMock(id=101, tenant_id=42, knowledge_id=9, file_name="new-a.pdf"),
        MagicMock(id=102, tenant_id=42, knowledge_id=10, file_name="new-b.pdf"),
    ]
    row_by_id = {int(row.id): row for row in file_rows}
    order: list[str] = []
    visibility = MagicMock()
    visibility.require_explicit_tenant = MagicMock(return_value=42)
    visibility.authoritative_mutation_space_ids = AsyncMock(
        side_effect=lambda **_kwargs: (order.append("canonical"), {})[1]
    )

    async def permit(_space_id, ids):
        order.append("permission")
        return set(ids)

    visibility.post_filter_rebac_visible_files = AsyncMock(side_effect=permit)
    visibility.filter_file_change_visible_ids = AsyncMock(return_value={101, 102})
    visibility.old_name_projection = AsyncMock(return_value={})

    file_repository = MagicMock()
    file_repository.find_by_ids_for_tenant = AsyncMock(return_value=file_rows)
    service = CitationResolveService(
        MagicMock(),
        knowledge_file_repository=file_repository,
    )
    service.runtime_cache_service.get_citations_by_ids = AsyncMock(return_value=items)
    service._build_visibility_service = MagicMock(return_value=visibility)

    with (
        patch(
            "bisheng.citation.domain.services.citation_resolve_service.KnowledgeFileDao.query_by_id_sync",
            side_effect=lambda file_id: row_by_id[int(file_id)],
        ),
        patch(
            "bisheng.citation.domain.services.citation_resolve_service.KnowledgeService.get_file_share_url",
            side_effect=lambda *_args: (order.append("url"), ("download", "preview"))[1],
        ),
        patch(
            "bisheng.citation.domain.services.citation_resolve_service.KnowledgeService.get_file_bbox",
            return_value=None,
        ),
    ):
        resolved = await service.resolve_citations(["a", "b"], _login_user(user_id=8))

    file_repository.find_by_ids_for_tenant.assert_awaited_once_with(
        tenant_id=42,
        entity_ids=[101, 102],
    )
    assert order[0] == "canonical"
    assert order.index("permission") < order.index("url")
    payloads = {item.citationId: item.sourcePayload for item in resolved}
    assert (payloads["a"].knowledgeId, payloads["a"].documentName) == (9, "new-a.pdf")
    assert payloads["a"].snippet == "from new-a.pdf"
    assert payloads["a"].items[0].content == "new-a.pdf body"
    assert (payloads["b"].knowledgeId, payloads["b"].documentName) == (10, "new-b.pdf")
    assert payloads["b"].snippet == "from new-b.pdf"
    assert payloads["b"].items[0].content == "new-b.pdf body"


async def test_preview_runs_view_file_before_stakeholder_preview_guard():
    set_current_tenant_id(42)
    service = KnowledgeSpaceService(request=MagicMock(), login_user=_login_user())
    file_record = MagicMock(
        id=101,
        knowledge_id=8,
        user_metadata={},
        file_source="upload",
    )
    order: list[str] = []

    async def get_file(*args, **kwargs):
        order.append("row-lookup")
        return file_record

    visibility = MagicMock()

    async def require_visible(**kwargs):
        assert kwargs == {
            "space_id": 8,
            "resource_id": 101,
            "allow_unpublished_stakeholder": True,
        }
        order.append("file-change")

    service._get_file_for_action = get_file
    visibility.require_file_change_visible = require_visible
    service._knowledge_file_visibility_service = visibility

    with patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeService.get_file_share_url",
        return_value=("original", "preview"),
    ):
        result = await service.get_file_preview(101)

    assert result["original_url"] == "original"
    assert order == ["row-lookup", "file-change"]


async def test_download_runs_download_permission_before_hard_file_change_guard():
    set_current_tenant_id(42)
    service = KnowledgeSpaceService(request=MagicMock(), login_user=_login_user())
    file_record = MagicMock(id=101, knowledge_id=8)
    order: list[str] = []

    async def get_file(*args, **kwargs):
        return file_record

    async def require_action(*args, **kwargs):
        order.append("download-permission")

    visibility = MagicMock()

    async def require_visible(**kwargs):
        assert kwargs == {"space_id": 8, "resource_id": 101}
        order.append("file-change")

    service._get_file_for_action = get_file
    service._require_action = require_action
    visibility.require_file_change_visible = require_visible
    service._knowledge_file_visibility_service = visibility

    with patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeService.get_file_share_url",
        return_value=("original", "preview"),
    ):
        result = await service.get_file_download(101, space_id=8)

    assert result == {"original_url": "original", "preview_url": "preview"}
    assert order == ["download-permission", "file-change"]


async def test_batch_download_visibility_helper_uses_one_guard_call_for_all_resources():
    set_current_tenant_id(42)
    service = KnowledgeSpaceService(request=MagicMock(), login_user=_login_user())
    visibility = MagicMock()
    visibility.filter_file_change_visible_ids = AsyncMock(return_value={101, 102, 103})
    service._knowledge_file_visibility_service = visibility

    await service._require_file_change_batch_visible(
        space_id=8,
        resource_ids=[101, 102, 101, 103],
    )

    visibility.filter_file_change_visible_ids.assert_awaited_once_with(
        space_ids=[8],
        resource_ids={101, 102, 103},
    )
