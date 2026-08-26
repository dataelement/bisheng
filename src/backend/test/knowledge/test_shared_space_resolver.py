"""F3 scope resolver tests (open-box, no live Milvus/ES/OpenFGA).

The resolver is tested against the frozen contract - any behaviour change from
the fake-resolver tests needs a contract-change PR.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from bisheng.knowledge.domain.contracts.errors import (
    SharedStorageContractError,
    SharedStorageErrorCode,
)
from bisheng.knowledge.domain.contracts.identifiers import (
    CanonicalDocumentId,
    CanonicalVersionId,
    EntryFileId,
    SpaceId,
    TenantId,
)
from bisheng.knowledge.domain.contracts.retrieval_scope import (
    BackendQueryFilter,
    CanonicalChunkHit,
    EntryRef,
    MappedEntryHit,
    RetrievalScope,
)
from bisheng.knowledge.domain.models.knowledge_file import (
    KnowledgeFile,
    KnowledgeFileEntryStatus,
    KnowledgeFileEntryType,
    KnowledgeFileProjectionStatus,
    KnowledgeFileStatus,
)
from bisheng.knowledge.domain.services.knowledge_scope_resolver import (
    KnowledgeSpaceScopeResolver,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _entry(
    entry_id: int,
    knowledge_id: int,
    tenant_id: int = 1,
    document_id: int = 100,
    entry_type: str = KnowledgeFileEntryType.MANAGER.value,
    projection_status: str = KnowledgeFileProjectionStatus.READY.value,
    entry_status: str = KnowledgeFileEntryStatus.ACTIVE.value,
) -> KnowledgeFile:
    return KnowledgeFile(
        id=entry_id,
        tenant_id=tenant_id,
        knowledge_id=knowledge_id,
        reference_document_id=document_id,
        entry_type=entry_type,
        entry_status=entry_status,
        projection_status=projection_status,
        file_type=1,
        status=KnowledgeFileStatus.SUCCESS.value,
        file_name=f"file_{entry_id}",
        user_id=1,
    )


def _chunk(
    doc_id: int = 100,
    version_id: int = 1000,
    chunk_index: int = 0,
    score: float = 0.95,
    text: str = "hello",
) -> CanonicalChunkHit:
    return CanonicalChunkHit(
        canonical_document_id=CanonicalDocumentId(doc_id),
        canonical_version_id=CanonicalVersionId(version_id),
        chunk_index=chunk_index,
        score=score,
        text=text,
    )


# ---------------------------------------------------------------------------
# resolve_request
# ---------------------------------------------------------------------------

class TestResolveRequest:
    async def test_visible_spaces_return_scope(self):
        """All requested spaces visible → valid scope."""
        repo = AsyncMock()
        perm_checker = AsyncMock(return_value={1, 2, 3})
        resolver = KnowledgeSpaceScopeResolver(
            file_repository=repo,
            permission_checker=perm_checker,
        )
        scope = await resolver.resolve_request(
            user_id="10",
            tenant_id=TenantId(1),
            space_ids=[SpaceId(1), SpaceId(2)],
        )
        assert scope.tenant_id == TenantId(1)
        assert scope.requested_space_ids == (SpaceId(1), SpaceId(2))
        assert scope.explicit_entry_ids_by_space == {}

    async def test_invisible_space_raises(self):
        """A space not in the visible set → SCOPE_SPACE_NOT_VISIBLE."""
        perm_checker = AsyncMock(return_value={1})
        resolver = KnowledgeSpaceScopeResolver(
            file_repository=AsyncMock(),
            permission_checker=perm_checker,
        )
        with pytest.raises(SharedStorageContractError) as exc:
            await resolver.resolve_request(
                user_id="10",
                tenant_id=TenantId(1),
                space_ids=[SpaceId(1), SpaceId(2)],
            )
        assert exc.value.code == SharedStorageErrorCode.SCOPE_SPACE_NOT_VISIBLE

    async def test_entry_ref_in_invisible_space_raises(self):
        """Explicit entry ref in an invisible space → ENTRY_REF_NOT_RESOLVABLE."""
        perm_checker = AsyncMock(return_value={1})
        resolver = KnowledgeSpaceScopeResolver(
            file_repository=AsyncMock(),
            permission_checker=perm_checker,
        )
        with pytest.raises(SharedStorageContractError) as exc:
            await resolver.resolve_request(
                user_id="10",
                tenant_id=TenantId(1),
                space_ids=[SpaceId(1)],
                entry_refs=[
                    EntryRef(space_id=SpaceId(2), entry_file_id=EntryFileId(100))
                ],
            )
        assert exc.value.code == SharedStorageErrorCode.ENTRY_REF_NOT_RESOLVABLE

    async def test_explicit_entry_refs_populated(self):
        """Valid explicit entry refs populate the scope."""
        perm_checker = AsyncMock(return_value={1, 2})
        resolver = KnowledgeSpaceScopeResolver(
            file_repository=AsyncMock(),
            permission_checker=perm_checker,
        )
        scope = await resolver.resolve_request(
            user_id="10",
            tenant_id=TenantId(1),
            space_ids=[SpaceId(1), SpaceId(2)],
            entry_refs=[
                EntryRef(space_id=SpaceId(1), entry_file_id=EntryFileId(100)),
                EntryRef(space_id=SpaceId(1), entry_file_id=EntryFileId(101)),
            ],
        )
        assert SpaceId(1) in scope.explicit_entry_ids_by_space
        assert len(scope.explicit_entry_ids_by_space[SpaceId(1)]) == 2

    async def test_empty_space_ids_raises(self):
        """Empty space_ids → SCOPE_SPACE_NOT_VISIBLE."""
        perm_checker = AsyncMock(return_value=set())
        resolver = KnowledgeSpaceScopeResolver(
            file_repository=AsyncMock(),
            permission_checker=perm_checker,
        )
        with pytest.raises(SharedStorageContractError) as exc:
            await resolver.resolve_request(
                user_id="10",
                tenant_id=TenantId(1),
                space_ids=[],
            )
        assert exc.value.code == SharedStorageErrorCode.SCOPE_SPACE_NOT_VISIBLE

    async def test_permission_checker_exception_fails_closed(self):
        """Permission checker crash → PERMISSION_SERVICE_UNAVAILABLE."""
        perm_checker = AsyncMock(side_effect=RuntimeError("boom"))
        resolver = KnowledgeSpaceScopeResolver(
            file_repository=AsyncMock(),
            permission_checker=perm_checker,
        )
        with pytest.raises(SharedStorageContractError) as exc:
            await resolver.resolve_request(
                user_id="10",
                tenant_id=TenantId(1),
                space_ids=[SpaceId(1)],
            )
        assert exc.value.code == SharedStorageErrorCode.PERMISSION_SERVICE_UNAVAILABLE


# ---------------------------------------------------------------------------
# build_backend_filter
# ---------------------------------------------------------------------------

class TestBuildBackendFilter:
    def test_basic_filter(self):
        resolver = KnowledgeSpaceScopeResolver(file_repository=AsyncMock())
        scope = RetrievalScope(
            tenant_id=TenantId(1),
            user_id="10",
            requested_space_ids=(SpaceId(1), SpaceId(2)),
            explicit_entry_ids_by_space={},
            routing_version=5,
        )
        f = resolver.build_backend_filter(scope)
        assert f.tenant_id == TenantId(1)
        assert f.requested_space_ids == (SpaceId(1), SpaceId(2))
        assert f.routing_version == 5
        assert f.canonical_document_ids is None
        assert f.canonical_version_ids is None

    def test_with_document_ids(self):
        resolver = KnowledgeSpaceScopeResolver(file_repository=AsyncMock())
        scope = RetrievalScope(
            tenant_id=TenantId(1),
            user_id="10",
            requested_space_ids=(SpaceId(1),),
            explicit_entry_ids_by_space={},
            routing_version=0,
        )
        f = resolver.build_backend_filter(
            scope,
            canonical_document_ids=[CanonicalDocumentId(100), CanonicalDocumentId(200)],
        )
        assert f.canonical_document_ids == (
            CanonicalDocumentId(100),
            CanonicalDocumentId(200),
        )


# ---------------------------------------------------------------------------
# map_and_authorize_hits
# ---------------------------------------------------------------------------

class TestMapAndAuthorizeHits:
    async def test_empty_hits_returns_empty(self):
        resolver = KnowledgeSpaceScopeResolver(file_repository=AsyncMock())
        scope = RetrievalScope(
            tenant_id=TenantId(1),
            user_id="10",
            requested_space_ids=(SpaceId(1),),
            explicit_entry_ids_by_space={},
            routing_version=0,
        )
        result = await resolver.map_and_authorize_hits(scope, [])
        assert result == ()

    async def test_single_document_dedup(self):
        """Two hits for the same document → only one mapped hit."""
        repo = AsyncMock()
        repo.find_active_entries_for_documents.return_value = [
            _entry(1, 1, document_id=100),
        ]
        resolver = KnowledgeSpaceScopeResolver(file_repository=repo)
        scope = RetrievalScope(
            tenant_id=TenantId(1),
            user_id="10",
            requested_space_ids=(SpaceId(1),),
            explicit_entry_ids_by_space={},
            routing_version=0,
        )
        with patch.object(
            resolver,
            "_final_authorize",
            new=AsyncMock(),
        ):
            result = await resolver.map_and_authorize_hits(
                scope,
                [_chunk(doc_id=100, chunk_index=0), _chunk(doc_id=100, chunk_index=1)],
            )
        assert len(result) == 1
        assert result[0].canonical_document_id == CanonicalDocumentId(100)

    async def test_explicit_entry_wins(self):
        """Explicit entry ref takes priority over space order."""
        # Two entries: one in space 1 (explicit), one in space 2 (first in order)
        repo = AsyncMock()
        repo.find_active_entries_for_documents.return_value = [
            _entry(1, 1, document_id=100, entry_type=KnowledgeFileEntryType.PUBLISH.value),
            _entry(2, 2, document_id=100, entry_type=KnowledgeFileEntryType.MANAGER.value),
        ]
        resolver = KnowledgeSpaceScopeResolver(file_repository=repo)
        scope = RetrievalScope(
            tenant_id=TenantId(1),
            user_id="10",
            requested_space_ids=(SpaceId(2), SpaceId(1)),  # space 2 is first
            explicit_entry_ids_by_space={
                SpaceId(1): (EntryFileId(1),),
            },
            routing_version=0,
        )
        with patch.object(
            resolver,
            "_final_authorize",
            new=AsyncMock(),
        ):
            result = await resolver.map_and_authorize_hits(
                scope,
                [_chunk(doc_id=100)],
            )
        assert len(result) == 1
        # Explicit entry in space 1 wins despite space 2 being first in order
        assert result[0].space_id == SpaceId(1)
        assert result[0].entry_file_id == EntryFileId(1)
        assert result[0].entry_selection_rule == "explicit"

    async def test_space_order_wins(self):
        """When no explicit ref, the first space in requested order wins."""
        repo = AsyncMock()
        repo.find_active_entries_for_documents.return_value = [
            _entry(1, 1, document_id=100, entry_type=KnowledgeFileEntryType.PUBLISH.value),
            _entry(2, 2, document_id=100, entry_type=KnowledgeFileEntryType.MANAGER.value),
        ]
        resolver = KnowledgeSpaceScopeResolver(file_repository=repo)
        scope = RetrievalScope(
            tenant_id=TenantId(1),
            user_id="10",
            requested_space_ids=(SpaceId(1), SpaceId(2)),
            explicit_entry_ids_by_space={},
            routing_version=0,
        )
        with patch.object(
            resolver,
            "_final_authorize",
            new=AsyncMock(),
        ):
            result = await resolver.map_and_authorize_hits(
                scope,
                [_chunk(doc_id=100)],
            )
        assert len(result) == 1
        # Space 1 is first in order → its entry wins
        assert result[0].space_id == SpaceId(1)
        assert result[0].entry_selection_rule == "space_order"

    async def test_entry_type_priority_in_same_space(self):
        """Within the same space, manager > publish > share."""
        repo = AsyncMock()
        repo.find_active_entries_for_documents.return_value = [
            _entry(1, 1, document_id=100, entry_type=KnowledgeFileEntryType.SHARE.value),
            _entry(2, 1, document_id=100, entry_type=KnowledgeFileEntryType.MANAGER.value),
        ]
        resolver = KnowledgeSpaceScopeResolver(file_repository=repo)
        scope = RetrievalScope(
            tenant_id=TenantId(1),
            user_id="10",
            requested_space_ids=(SpaceId(1),),
            explicit_entry_ids_by_space={},
            routing_version=0,
        )
        with patch.object(
            resolver,
            "_final_authorize",
            new=AsyncMock(),
        ):
            result = await resolver.map_and_authorize_hits(
                scope,
                [_chunk(doc_id=100)],
            )
        assert len(result) == 1
        assert result[0].entry_file_id == EntryFileId(2)  # manager wins

    async def test_no_candidates_skipped(self):
        """Document with no visible entries → skipped."""
        repo = AsyncMock()
        repo.find_active_entries_for_documents.return_value = []
        resolver = KnowledgeSpaceScopeResolver(file_repository=repo)
        scope = RetrievalScope(
            tenant_id=TenantId(1),
            user_id="10",
            requested_space_ids=(SpaceId(1),),
            explicit_entry_ids_by_space={},
            routing_version=0,
        )
        result = await resolver.map_and_authorize_hits(
            scope,
            [_chunk(doc_id=100)],
        )
        assert result == ()

    async def test_not_projection_ready_skipped(self):
        """Entry not projection-ready → skipped."""
        repo = AsyncMock()
        repo.find_active_entries_for_documents.return_value = [
            _entry(
                1,
                1,
                document_id=100,
                projection_status=KnowledgeFileProjectionStatus.PROJECTING.value,
            ),
        ]
        resolver = KnowledgeSpaceScopeResolver(file_repository=repo)
        scope = RetrievalScope(
            tenant_id=TenantId(1),
            user_id="10",
            requested_space_ids=(SpaceId(1),),
            explicit_entry_ids_by_space={},
            routing_version=0,
        )
        result = await resolver.map_and_authorize_hits(
            scope,
            [_chunk(doc_id=100)],
        )
        assert result == ()

    async def test_final_authorize_denied_raises(self):
        """Final authorize fails → PERMISSION_DENIED propagated."""
        repo = AsyncMock()
        repo.find_active_entries_for_documents.return_value = [
            _entry(1, 1, document_id=100),
        ]
        resolver = KnowledgeSpaceScopeResolver(file_repository=repo)
        scope = RetrievalScope(
            tenant_id=TenantId(1),
            user_id="10",
            requested_space_ids=(SpaceId(1),),
            explicit_entry_ids_by_space={},
            routing_version=0,
        )
        with patch.object(
            resolver,
            "_final_authorize",
            side_effect=SharedStorageContractError(
                SharedStorageErrorCode.PERMISSION_DENIED,
                "denied",
                tenant_id=1,
            ),
        ):
            with pytest.raises(SharedStorageContractError) as exc:
                await resolver.map_and_authorize_hits(
                    scope,
                    [_chunk(doc_id=100)],
                )
            assert exc.value.code == SharedStorageErrorCode.PERMISSION_DENIED

    async def test_multiple_documents_distinct(self):
        """Two different documents → two mapped hits."""
        repo = AsyncMock()
        repo.find_active_entries_for_documents.return_value = [
            _entry(1, 1, document_id=100),
            _entry(2, 2, document_id=200),
        ]
        resolver = KnowledgeSpaceScopeResolver(file_repository=repo)
        scope = RetrievalScope(
            tenant_id=TenantId(1),
            user_id="10",
            requested_space_ids=(SpaceId(1), SpaceId(2)),
            explicit_entry_ids_by_space={},
            routing_version=0,
        )
        with patch.object(
            resolver,
            "_final_authorize",
            new=AsyncMock(),
        ):
            result = await resolver.map_and_authorize_hits(
                scope,
                [_chunk(doc_id=100), _chunk(doc_id=200)],
            )
        assert len(result) == 2
        doc_ids = {int(hit.canonical_document_id) for hit in result}
        assert doc_ids == {100, 200}


# ---------------------------------------------------------------------------
# _check_single_space (real path, via mocked KnowledgeSpaceService)
# ---------------------------------------------------------------------------

class TestCheckSingleSpace:
    async def test_visible_space_returns_true(self):
        resolver = KnowledgeSpaceScopeResolver(file_repository=AsyncMock())
        with patch(
            "bisheng.knowledge.domain.services.knowledge_scope_resolver.KnowledgeSpaceService",
        ) as mock_svc:
            mock_svc._user_can_read_space = AsyncMock(return_value=True)
            result = await resolver._check_single_space(
                user_id=10,
                tenant_id=1,
                space_id=1,
            )
        assert result is True

    async def test_invisible_space_returns_false(self):
        resolver = KnowledgeSpaceScopeResolver(file_repository=AsyncMock())
        with patch(
            "bisheng.knowledge.domain.services.knowledge_scope_resolver.KnowledgeSpaceService",
        ) as mock_svc:
            mock_svc._user_can_read_space = AsyncMock(return_value=False)
            result = await resolver._check_single_space(
                user_id=10,
                tenant_id=1,
                space_id=1,
            )
        assert result is False

    async def test_exception_propagates(self):
        resolver = KnowledgeSpaceScopeResolver(file_repository=AsyncMock())
        with patch(
            "bisheng.knowledge.domain.services.knowledge_scope_resolver.KnowledgeSpaceService",
        ) as mock_svc:
            mock_svc._user_can_read_space = AsyncMock(
                side_effect=RuntimeError("OpenFGA down")
            )
            with pytest.raises(RuntimeError):
                await resolver._check_single_space(
                    user_id=10,
                    tenant_id=1,
                    space_id=1,
                )