"""M0 contract freeze tests: invariants of the frozen shared-storage contracts.

These tests pin the contract semantics themselves. Changing behaviour here
requires a contract-change PR (task-breakdown document, section 7-1).
"""
from __future__ import annotations

import pytest

from bisheng.knowledge.domain.contracts import (
    SHARED_SPACE_CONTENT_METADATA_SCHEMA,
    ContentProjectionIdentity,
    ContentUpsertRequest,
    MembershipUpdateRequest,
    ProjectionReadiness,
    SharedContentChunk,
    validate_knowledge_ids,
)
from bisheng.knowledge.domain.contracts.errors import (
    SharedStorageContractError,
    SharedStorageErrorCode,
)
from bisheng.knowledge.domain.contracts.identifiers import (
    CanonicalDocumentId,
    CanonicalVersionId,
    ContentFileId,
    TenantId,
)
from test.fakes.shared_storage_fakes import (
    FakeKnowledgeRetrievalScopeResolver,
    FakeProjectionReadinessService,
    FakeSharedSpaceStorageWriter,
)


class TestValidateKnowledgeIds:
    def test_normalises_valid_input(self):
        assert validate_knowledge_ids([1, 2, 3]) == (1, 2, 3)

    def test_rejects_empty_without_allow_empty(self):
        with pytest.raises(SharedStorageContractError) as exc:
            validate_knowledge_ids([])
        assert exc.value.code == SharedStorageErrorCode.EMPTY_MEMBERSHIP

    def test_allows_empty_when_tombstone(self):
        assert validate_knowledge_ids([], allow_empty=True) == ()

    def test_rejects_unsorted_or_duplicated(self):
        with pytest.raises(ValueError):
            validate_knowledge_ids([2, 1])
        with pytest.raises(ValueError):
            validate_knowledge_ids([1, 1])


class TestSharedMetadataSchema:
    def test_knowledge_ids_is_non_nullable_int64_array(self):
        field = next(
            f
            for f in SHARED_SPACE_CONTENT_METADATA_SCHEMA
            if f.field_name == "knowledge_ids"
        )
        assert field.field_type == "array_int64"
        assert field.kwargs["nullable"] is False
        assert field.kwargs["element_type"] == "int64"
        assert 1 <= field.kwargs["max_capacity"] <= 4096

    def test_identity_fields_present_and_non_nullable(self):
        by_name = {f.field_name: f for f in SHARED_SPACE_CONTENT_METADATA_SCHEMA}
        for name in (
            "tenant_id",
            "canonical_document_id",
            "canonical_version_id",
            "content_file_id",
            "chunk_index",
            "content_generation",
        ):
            assert by_name[name].kwargs["nullable"] is False, name


class TestFakeSharedSpaceStorageWriter:
    def _identity(self, generation: int = 1) -> ContentProjectionIdentity:
        return ContentProjectionIdentity(
            tenant_id=TenantId(1),
            canonical_document_id=CanonicalDocumentId(10),
            canonical_version_id=CanonicalVersionId(100),
            content_file_id=ContentFileId(1000),
            content_generation=generation,
        )

    async def test_upsert_stores_single_copy(self):
        writer = FakeSharedSpaceStorageWriter()
        await writer.upsert_content(
            ContentUpsertRequest(
                identity=self._identity(),
                knowledge_ids=(1,),
                chunks=[SharedContentChunk(chunk_index=0, text="hello")],
            )
        )
        assert writer.chunk_count(1, 10) == 1
        assert writer.membership_of(1, 10) == (1,)

    async def test_membership_rewrite_touches_all_chunks_without_reembedding(self):
        writer = FakeSharedSpaceStorageWriter()
        await writer.upsert_content(
            ContentUpsertRequest(
                identity=self._identity(),
                knowledge_ids=(1,),
                chunks=[
                    SharedContentChunk(chunk_index=0, text="a"),
                    SharedContentChunk(chunk_index=1, text="b"),
                ],
            )
        )
        await writer.update_membership(
            MembershipUpdateRequest(
                tenant_id=TenantId(1),
                canonical_document_id=CanonicalDocumentId(10),
                knowledge_ids=(1, 2),
                membership_generation=2,
                content_generation=1,
            )
        )
        assert writer.membership_of(1, 10) == (1, 2)
        # original vector payload untouched (no re-embedding)
        for chunks in writer.content.values():
            for chunk in chunks.values():
                assert chunk["knowledge_ids"] == [1, 2]

    async def test_empty_membership_is_tombstone_not_empty_array(self):
        writer = FakeSharedSpaceStorageWriter()
        await writer.upsert_content(
            ContentUpsertRequest(
                identity=self._identity(),
                knowledge_ids=(1,),
                chunks=[SharedContentChunk(chunk_index=0, text="x")],
            )
        )
        await writer.update_membership(
            MembershipUpdateRequest(
                tenant_id=TenantId(1),
                canonical_document_id=CanonicalDocumentId(10),
                knowledge_ids=(),
                membership_generation=3,
                content_generation=1,
            )
        )
        assert writer.chunk_count(1, 10) == 0
        assert writer.membership_of(1, 10) is None

    async def test_stale_membership_generation_rejected(self):
        writer = FakeSharedSpaceStorageWriter()
        await writer.update_membership(
            MembershipUpdateRequest(
                tenant_id=TenantId(1),
                canonical_document_id=CanonicalDocumentId(10),
                knowledge_ids=(1,),
                membership_generation=5,
                content_generation=1,
            )
        )
        with pytest.raises(SharedStorageContractError):
            await writer.update_membership(
                MembershipUpdateRequest(
                    tenant_id=TenantId(1),
                    canonical_document_id=CanonicalDocumentId(10),
                    knowledge_ids=(1, 2),
                    membership_generation=4,
                    content_generation=1,
                )
            )


class TestFakeRetrievalScopeResolver:
    async def test_invisible_space_fails_closed(self):
        resolver = FakeKnowledgeRetrievalScopeResolver(
            visible_spaces={"1:u1": {11}},
        )
        with pytest.raises(SharedStorageContractError) as exc:
            await resolver.resolve_request(
                user_id="u1", tenant_id=TenantId(1), space_ids=[11, 12]
            )
        assert exc.value.code == SharedStorageErrorCode.SCOPE_SPACE_NOT_VISIBLE

    async def test_hits_deduplicated_with_entry_selection_priority(self):
        from bisheng.knowledge.domain.contracts import CanonicalChunkHit, EntryRef

        resolver = FakeKnowledgeRetrievalScopeResolver(
            visible_spaces={"1:u1": {11, 12}},
            entries_by_document={
                (1, 10): [(11, 111, "publish"), (12, 121, "manager")],
            },
        )
        scope = await resolver.resolve_request(
            user_id="u1",
            tenant_id=TenantId(1),
            space_ids=[11, 12],
            entry_refs=[EntryRef(space_id=11, entry_file_id=111)],
        )
        hits = [
            CanonicalChunkHit(
                canonical_document_id=CanonicalDocumentId(10),
                canonical_version_id=CanonicalVersionId(100),
                chunk_index=0,
                score=0.9,
            )
        ]
        mapped = await resolver.map_and_authorize_hits(scope, hits)
        assert len(mapped) == 1
        # explicit entry wins over manager priority in a later space
        assert mapped[0].space_id == 11
        assert mapped[0].entry_file_id == 111
        assert mapped[0].entry_selection_rule == "explicit"


class TestFakeReadinessService:
    async def test_default_ready_and_per_entry_override(self):
        service = FakeProjectionReadinessService()
        result = await service.get_content_membership_readiness(
            tenant_id=TenantId(1), entry_file_id=5
        )
        assert isinstance(result, ProjectionReadiness)
        assert result.ready is True
        assert result.reason is None

        service.set_result(
            (1, 5),
            ProjectionReadiness(
                ready=False,
                reason=SharedStorageErrorCode.MEMBERSHIP_PROJECTION_NOT_READY,
            ),
        )
        result = await service.get_content_membership_readiness(
            tenant_id=TenantId(1), entry_file_id=5
        )
        assert result.ready is False
        assert result.reason == SharedStorageErrorCode.MEMBERSHIP_PROJECTION_NOT_READY
