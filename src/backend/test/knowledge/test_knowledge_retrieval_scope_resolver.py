"""F3 retrieval scope resolver tests (refactor spec 3.5/3.6/8.1, POC-3 list).

All tests run against in-memory stub repositories and permission checkers -
no Milvus/ES/OpenFGA dependency. Scenario coverage follows the POC-3 entry
back-mapping list: manager+publish+share coexisting, one user visible in
several spaces, chained A->B->C publishes, primary version switch, share
revocation, folder moves, soft delete / projection pending, cross-tenant
id rejection, explicit-entry selection and over-fetch refill of Top-K.
"""
from __future__ import annotations

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

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
    CanonicalGenerationConstraint,
    EntryRef,
    MappedEntryHit,
    RetrievalScope,
)
from bisheng.knowledge.domain.models.knowledge_document import (
    KnowledgeDocument,
    KnowledgeDocumentLifecycleStatus,
)
from bisheng.knowledge.domain.models.knowledge_document_version import (
    KnowledgeDocumentVersion,
)
from bisheng.knowledge.domain.models.knowledge_file import (
    KnowledgeFile,
    KnowledgeFileEntryStatus,
    KnowledgeFileEntryType,
    KnowledgeFileProjectionStatus,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)
from bisheng.knowledge.domain.services.knowledge_retrieval_scope_resolver import (
    RetrievalScopeResolverSettings,
    SqlKnowledgeRetrievalScopeResolver,
    render_es_membership_query,
    render_milvus_expr,
)

TENANT = 7
USER = "42"
DOC = 91
V1 = 501
V2 = 502

ENABLED_SETTINGS = RetrievalScopeResolverSettings(
    enabled=True,
    routing_version=1,
    overfetch_factor=2,
    max_overfetch_rounds=4,
)


# ---------------------------------------------------------------------------
# stub repositories / checkers
# ---------------------------------------------------------------------------
class StubFileRepository:
    def __init__(self, entries: list[KnowledgeFile]):
        self.entries = list(entries)
        self.mapping_calls: list[tuple[int, tuple[int, ...], tuple[int, ...]]] = []

    async def find_by_ids(self, entity_ids: list[int]):
        wanted = set(int(i) for i in entity_ids)
        return [e for e in self.entries if int(e.id) in wanted]

    async def find_active_entries_for_documents(
        self,
        *,
        tenant_id: int,
        document_ids: list[int],
        knowledge_ids: list[int],
    ) -> list[KnowledgeFile]:
        self.mapping_calls.append(
            (tenant_id, tuple(sorted(set(document_ids))), tuple(sorted(set(knowledge_ids))))
        )
        docs = {int(d) for d in document_ids}
        spaces = set(int(k) for k in knowledge_ids)
        return [
            e
            for e in self.entries
            if int(e.tenant_id or 0) == tenant_id
            and int(e.reference_document_id or 0) in docs
            and int(e.knowledge_id) in spaces
            and e.entry_status == KnowledgeFileEntryStatus.ACTIVE.value
            and e.entry_type in {"manager", "publish", "share"}
        ]

    async def find_active_entries_for_documents_any_space(
        self,
        *,
        tenant_id: int,
        document_ids: list[int],
    ) -> list[KnowledgeFile]:
        docs = set(int(d) for d in document_ids)
        return [
            e
            for e in self.entries
            if int(e.tenant_id or 0) == tenant_id
            and int(e.reference_document_id or 0) in docs
            and e.entry_status == KnowledgeFileEntryStatus.ACTIVE.value
            and e.entry_type in {"manager", "publish", "share"}
        ]


class StubDocumentRepository:
    def __init__(self, documents: list[KnowledgeDocument]):
        self.documents = list(documents)

    async def find_by_ids(self, entity_ids: list[int]):
        wanted = set(int(i) for i in entity_ids)
        return [d for d in self.documents if int(d.id) in wanted]


class StubVersionRepository:
    def __init__(self, versions: list[KnowledgeDocumentVersion]):
        self.versions = list(versions)

    async def find_by_knowledge_file_id(self, knowledge_file_id: int):
        for v in self.versions:
            if int(v.knowledge_file_id) == int(knowledge_file_id):
                return v
        return None


class RecordingSpaceChecker:
    def __init__(self, allowed_spaces: set[int], *, error: Exception | None = None):
        self.allowed_spaces = allowed_spaces
        self.error = error
        self.calls: list[int] = []

    async def __call__(self, tenant_id, user_id, space_id) -> bool:
        self.calls.append(int(space_id))
        if self.error is not None:
            raise self.error
        return int(space_id) in self.allowed_spaces


class RecordingEntryChecker:
    def __init__(self, denied_entries: set[int] | None = None, *, error: Exception | None = None):
        self.denied_entries = denied_entries or set()
        self.error = error
        self.calls: list[tuple[int, int]] = []

    async def __call__(self, tenant_id, user_id, space_id, entry_file_id) -> bool:
        self.calls.append((int(space_id), int(entry_file_id)))
        if self.error is not None:
            raise self.error
        return int(entry_file_id) not in self.denied_entries


def make_entry(
    entry_id: int,
    *,
    space_id: int,
    entry_type: str | None,
    document_id: int | None = DOC,
    tenant_id: int = TENANT,
    status: str = KnowledgeFileEntryStatus.ACTIVE.value,
    projection: str = KnowledgeFileProjectionStatus.READY.value,
    desired_content: int = 1,
    applied_content: int = 1,
    desired_entry: int = 1,
    applied_entry: int = 1,
    file_level_path: str | None = None,
) -> KnowledgeFile:
    return KnowledgeFile(
        id=entry_id,
        tenant_id=tenant_id,
        knowledge_id=space_id,
        file_name="doc.pdf",
        reference_document_id=document_id,
        entry_type=entry_type,
        entry_status=status,
        projection_status=projection,
        desired_content_generation=desired_content,
        applied_content_generation=applied_content,
        desired_entry_generation=desired_entry,
        applied_entry_generation=applied_entry,
        file_level_path=file_level_path,
    )


def make_document(
    document_id: int = DOC,
    *,
    space_id: int = 20,
    primary_version_id: int | None = V1,
    tenant_id: int = TENANT,
    lifecycle: str = KnowledgeDocumentLifecycleStatus.ACTIVE.value,
) -> KnowledgeDocument:
    return KnowledgeDocument(
        id=document_id,
        tenant_id=tenant_id,
        knowledge_id=space_id,
        primary_version_id=primary_version_id,
        lifecycle_status=lifecycle,
        content_generation=1,
    )


def make_resolver(
    *,
    entries: list[KnowledgeFile] | None = None,
    documents: list[KnowledgeDocument] | None = None,
    versions: list[KnowledgeDocumentVersion] | None = None,
    allowed_spaces: set[int] | None = None,
    space_error: Exception | None = None,
    denied_entries: set[int] | None = None,
    entry_error: Exception | None = None,
    settings: RetrievalScopeResolverSettings | None = None,
) -> tuple[
    SqlKnowledgeRetrievalScopeResolver,
    StubFileRepository,
    RecordingSpaceChecker,
    RecordingEntryChecker,
]:
    file_repo = StubFileRepository(entries or [])
    space_checker = RecordingSpaceChecker(
        allowed_spaces if allowed_spaces is not None else {10, 20, 30, 40},
        error=space_error,
    )
    entry_checker = RecordingEntryChecker(denied_entries, error=entry_error)
    resolver = SqlKnowledgeRetrievalScopeResolver(
        file_repository=file_repo,
        document_repository=StubDocumentRepository(documents or []),
        version_repository=StubVersionRepository(versions or []),
        space_read_checker=space_checker,
        entry_view_checker=entry_checker,
        settings_provider=lambda: settings or ENABLED_SETTINGS,
    )
    return resolver, file_repo, space_checker, entry_checker


def make_scope(
    *,
    space_ids: tuple[int, ...] = (20, 10),
    explicit: dict[int, tuple[int, ...]] | None = None,
    user_id: str = USER,
    tenant_id: int = TENANT,
    routing_version: int = 1,
) -> RetrievalScope:
    return RetrievalScope(
        tenant_id=TenantId(tenant_id),
        user_id=user_id,
        requested_space_ids=tuple(SpaceId(s) for s in space_ids),
        explicit_entry_ids_by_space={
            SpaceId(k): tuple(EntryFileId(i) for i in v) for k, v in (explicit or {}).items()
        },
        routing_version=routing_version,
    )


def hit(
    document_id: int = DOC,
    version_id: int = V1,
    chunk_index: int = 0,
    score: float = 0.9,
    text: str | None = "chunk text",
    content_generation: int = 1,
    membership_generation: int = 1,
) -> CanonicalChunkHit:
    return CanonicalChunkHit(
        canonical_document_id=CanonicalDocumentId(document_id),
        canonical_version_id=CanonicalVersionId(version_id),
        chunk_index=chunk_index,
        score=score,
        text=text,
        content_generation=content_generation,
        membership_generation=membership_generation,
    )


def default_mapping_fixture(
    entries: list[KnowledgeFile],
    documents: list[KnowledgeDocument] | None = None,
    denied_entries: set[int] | None = None,
):
    resolver, file_repo, _, entry_checker = make_resolver(
        entries=entries,
        documents=documents if documents is not None else [make_document()],
        denied_entries=denied_entries,
    )
    return resolver, file_repo, entry_checker


# ---------------------------------------------------------------------------
# F3.1 scope resolution
# ---------------------------------------------------------------------------
async def test_resolve_request_whole_space_does_not_expand_file_ids():
    resolver, _, space_checker, _ = make_resolver()

    scope = await resolver.resolve_request(
        user_id=USER,
        tenant_id=TenantId(TENANT),
        space_ids=[SpaceId(20), SpaceId(10), SpaceId(20)],
    )

    assert scope.requested_space_ids == (SpaceId(20), SpaceId(10))
    assert dict(scope.explicit_entry_ids_by_space) == {}
    assert scope.routing_version == 1
    assert space_checker.calls == [20, 10]
    # Whole-space requests must not touch the file repository at all.
    assert resolver.file_repository.mapping_calls == []


async def test_resolve_request_space_not_visible_fails_closed():
    resolver, _, _, _ = make_resolver(allowed_spaces={20})

    with pytest.raises(SharedStorageContractError) as exc_info:
        await resolver.resolve_request(
            user_id=USER,
            tenant_id=TenantId(TENANT),
            space_ids=[SpaceId(20), SpaceId(10)],
        )
    assert exc_info.value.code == SharedStorageErrorCode.SCOPE_SPACE_NOT_VISIBLE
    assert exc_info.value.tenant_id == TENANT


async def test_resolve_request_permission_service_unavailable_fails_closed():
    resolver, _, _, _ = make_resolver(space_error=RuntimeError("openfga down"))

    with pytest.raises(SharedStorageContractError) as exc_info:
        await resolver.resolve_request(
            user_id=USER,
            tenant_id=TenantId(TENANT),
            space_ids=[SpaceId(20)],
        )
    assert exc_info.value.code == SharedStorageErrorCode.PERMISSION_SERVICE_UNAVAILABLE


async def test_resolve_request_keeps_explicit_refs_per_space():
    resolver, _, _, _ = make_resolver(
        entries=[
            make_entry(100, space_id=20, entry_type=KnowledgeFileEntryType.MANAGER.value),
            make_entry(101, space_id=10, entry_type=KnowledgeFileEntryType.PUBLISH.value),
        ]
    )

    scope = await resolver.resolve_request(
        user_id=USER,
        tenant_id=TenantId(TENANT),
        space_ids=[SpaceId(20), SpaceId(10)],
        entry_refs=[
            EntryRef(space_id=SpaceId(10), entry_file_id=EntryFileId(101)),
            EntryRef(space_id=SpaceId(20), entry_file_id=EntryFileId(100)),
            EntryRef(space_id=SpaceId(10), entry_file_id=EntryFileId(101)),
        ],
    )

    assert dict(scope.explicit_entry_ids_by_space) == {
        SpaceId(10): (EntryFileId(101),),
        SpaceId(20): (EntryFileId(100),),
    }


async def test_resolve_request_rejects_ref_outside_requested_spaces():
    resolver, _, _, _ = make_resolver()

    with pytest.raises(SharedStorageContractError) as exc_info:
        await resolver.resolve_request(
            user_id=USER,
            tenant_id=TenantId(TENANT),
            space_ids=[SpaceId(20)],
            entry_refs=[EntryRef(space_id=SpaceId(30), entry_file_id=EntryFileId(101))],
        )
    assert exc_info.value.code == SharedStorageErrorCode.ENTRY_REF_NOT_RESOLVABLE


async def test_resolve_request_rejects_cross_tenant_entry_ref():
    resolver, _, _, _ = make_resolver(
        entries=[
            make_entry(101, space_id=20, entry_type=KnowledgeFileEntryType.PUBLISH.value, tenant_id=99),
        ]
    )

    with pytest.raises(SharedStorageContractError) as exc_info:
        await resolver.resolve_request(
            user_id=USER,
            tenant_id=TenantId(TENANT),
            space_ids=[SpaceId(20)],
            entry_refs=[EntryRef(space_id=SpaceId(20), entry_file_id=EntryFileId(101))],
        )
    assert exc_info.value.code == SharedStorageErrorCode.ENTRY_REF_NOT_RESOLVABLE
    assert exc_info.value.tenant_id == TENANT


async def test_resolve_request_rejects_inactive_entry_ref():
    resolver, _, _, _ = make_resolver(
        entries=[
            make_entry(
                102,
                space_id=20,
                entry_type=KnowledgeFileEntryType.SHARE.value,
                status=KnowledgeFileEntryStatus.DELETING.value,
            ),
        ]
    )

    with pytest.raises(SharedStorageContractError) as exc_info:
        await resolver.resolve_request(
            user_id=USER,
            tenant_id=TenantId(TENANT),
            space_ids=[SpaceId(20)],
            entry_refs=[EntryRef(space_id=SpaceId(20), entry_file_id=EntryFileId(102))],
        )
    assert exc_info.value.code == SharedStorageErrorCode.ENTRY_REF_NOT_RESOLVABLE


async def test_resolver_fails_closed_when_feature_disabled():
    resolver, _, _, _ = make_resolver(settings=RetrievalScopeResolverSettings(enabled=False))

    for action in (
        resolver.resolve_request(
            user_id=USER, tenant_id=TenantId(TENANT), space_ids=[SpaceId(20)]
        ),
        resolver.map_and_authorize_hits(make_scope(), [hit()]),
    ):
        with pytest.raises(SharedStorageContractError) as exc_info:
            await action
        assert exc_info.value.code == SharedStorageErrorCode.SHARED_STORAGE_NOT_ENABLED

    with pytest.raises(SharedStorageContractError) as exc_info:
        resolver.build_backend_filter(make_scope())
    assert exc_info.value.code == SharedStorageErrorCode.SHARED_STORAGE_NOT_ENABLED


# ---------------------------------------------------------------------------
# F3.2 filter builder + renderers
# ---------------------------------------------------------------------------
async def test_build_backend_filter_carries_tenant_spaces_and_narrowing():
    resolver, _, _, _ = make_resolver()
    scope = make_scope(space_ids=(20, 10), explicit={20: (100,)})
    generation_constraint = CanonicalGenerationConstraint(
        canonical_document_id=CanonicalDocumentId(DOC),
        canonical_version_id=CanonicalVersionId(V1),
        content_generation=1,
        membership_generation=2,
    )

    query_filter = resolver.build_backend_filter(
        scope,
        canonical_document_ids=[CanonicalDocumentId(DOC), CanonicalDocumentId(DOC)],
        canonical_version_ids=[CanonicalVersionId(V1)],
        generation_constraints=[generation_constraint],
    )

    assert isinstance(query_filter, BackendQueryFilter)
    assert int(query_filter.tenant_id) == TENANT
    assert tuple(int(s) for s in query_filter.requested_space_ids) == (20, 10)
    assert query_filter.canonical_document_ids == (CanonicalDocumentId(DOC),)
    assert query_filter.canonical_version_ids == (CanonicalVersionId(V1),)
    assert query_filter.generation_constraints == (generation_constraint,)
    assert query_filter.routing_version == scope.routing_version


async def test_build_backend_filter_rejects_stale_routing_version():
    resolver, _, _, _ = make_resolver()

    with pytest.raises(SharedStorageContractError) as exc_info:
        resolver.build_backend_filter(make_scope(routing_version=0))
    assert exc_info.value.code == SharedStorageErrorCode.ROUTING_VERSION_MISMATCH


async def test_current_generation_constraint_uses_all_active_memberships():
    entries = [
        make_entry(100, space_id=10, entry_type=KnowledgeFileEntryType.MANAGER.value),
        make_entry(
            200,
            space_id=20,
            entry_type=KnowledgeFileEntryType.PUBLISH.value,
            desired_entry=3,
            applied_entry=3,
        ),
    ]
    resolver, _, _, _ = make_resolver(
        entries=entries,
        documents=[make_document(primary_version_id=V1)],
    )

    constraints = await resolver.resolve_current_generation_constraints(
        make_scope(space_ids=(10,)),
        [CanonicalDocumentId(DOC)],
    )

    assert len(constraints) == 1
    assert int(constraints[0].canonical_version_id) == V1
    assert constraints[0].content_generation == 1
    assert constraints[0].membership_generation == 3


async def test_render_milvus_expr_single_and_multi_space():
    single = BackendQueryFilter(
        tenant_id=TenantId(TENANT),
        requested_space_ids=(SpaceId(20),),
        routing_version=1,
    )
    assert (
        render_milvus_expr(single)
        == f"tenant_id == {TENANT} and ARRAY_CONTAINS(knowledge_ids, 20)"
    )

    multi = BackendQueryFilter(
        tenant_id=TenantId(TENANT),
        requested_space_ids=(SpaceId(20), SpaceId(10)),
        routing_version=1,
        canonical_document_ids=(CanonicalDocumentId(DOC),),
        canonical_version_ids=(CanonicalVersionId(V1),),
    )
    assert (
        render_milvus_expr(multi)
        == f"tenant_id == {TENANT} and ARRAY_CONTAINS_ANY(knowledge_ids, [20, 10]) "
        f"and canonical_document_id in [{DOC}] and canonical_version_id in [{V1}]"
    )

    with pytest.raises(ValueError):
        render_milvus_expr(
            BackendQueryFilter(
                tenant_id=TenantId(TENANT),
                requested_space_ids=(),
                routing_version=1,
            )
        )


async def test_render_es_membership_query():
    query_filter = BackendQueryFilter(
        tenant_id=TenantId(TENANT),
        requested_space_ids=(SpaceId(20), SpaceId(10)),
        routing_version=1,
        canonical_document_ids=(CanonicalDocumentId(DOC),),
    )
    assert render_es_membership_query(query_filter) == {
        "bool": {
            "filter": [
                {"term": {"metadata.tenant_id": TENANT}},
                {"terms": {"metadata.knowledge_ids": [20, 10]}},
                {"terms": {"metadata.canonical_document_id": [DOC]}},
            ]
        }
    }


# ---------------------------------------------------------------------------
# F3.3 / F3.5 / F3.6 mapping, final checks, dedupe, selection
# ---------------------------------------------------------------------------
async def test_manager_publish_share_coexisting_pick_entry_type_priority():
    entries = [
        make_entry(100, space_id=20, entry_type=KnowledgeFileEntryType.MANAGER.value),
        make_entry(101, space_id=20, entry_type=KnowledgeFileEntryType.PUBLISH.value),
        make_entry(102, space_id=20, entry_type=KnowledgeFileEntryType.SHARE.value),
    ]
    resolver, file_repo, _ = default_mapping_fixture(entries)

    mapped = await resolver.map_and_authorize_hits(make_scope(space_ids=(20,)), [hit()])

    assert len(mapped) == 1
    assert int(mapped[0].entry_file_id) == 100  # manager wins within one space
    assert mapped[0].entry_selection_rule == "entry_type_priority"
    # O(Top-K): exactly one batched entry query for the hit document set.
    assert file_repo.mapping_calls == [(TENANT, (DOC,), (20,))]


async def test_multi_space_visibility_uses_requested_space_order():
    entries = [
        make_entry(100, space_id=20, entry_type=KnowledgeFileEntryType.MANAGER.value),
        make_entry(101, space_id=10, entry_type=KnowledgeFileEntryType.PUBLISH.value),
    ]
    resolver, _, _ = default_mapping_fixture(entries)

    mapped = await resolver.map_and_authorize_hits(make_scope(space_ids=(10, 20)), [hit()])

    assert (int(mapped[0].space_id), int(mapped[0].entry_file_id)) == (10, 101)
    assert mapped[0].entry_selection_rule == "space_order"


async def test_chained_a_b_c_publish_maps_to_surviving_entry():
    entries = [
        make_entry(
            100,
            space_id=10,
            entry_type=KnowledgeFileEntryType.PUBLISH.value,
            status=KnowledgeFileEntryStatus.INVALID.value,
        ),
        make_entry(
            101,
            space_id=20,
            entry_type=KnowledgeFileEntryType.PUBLISH.value,
            status=KnowledgeFileEntryStatus.DELETING.value,
        ),
        make_entry(102, space_id=30, entry_type=KnowledgeFileEntryType.MANAGER.value),
    ]
    resolver, _, _ = default_mapping_fixture(entries)

    mapped = await resolver.map_and_authorize_hits(make_scope(space_ids=(10, 20, 30)), [hit()])

    assert len(mapped) == 1
    assert (int(mapped[0].space_id), int(mapped[0].entry_file_id)) == (30, 102)


async def test_explicit_entry_wins_over_space_order():
    entries = [
        make_entry(100, space_id=10, entry_type=KnowledgeFileEntryType.MANAGER.value),
        make_entry(101, space_id=20, entry_type=KnowledgeFileEntryType.SHARE.value),
    ]
    resolver, _, _ = default_mapping_fixture(entries)

    scope = make_scope(space_ids=(10, 20), explicit={20: (101,)})
    mapped = await resolver.map_and_authorize_hits(scope, [hit()])

    assert (int(mapped[0].space_id), int(mapped[0].entry_file_id)) == (20, 101)
    assert mapped[0].entry_selection_rule == "explicit"


async def test_share_revocation_blocks_hit_at_final_check():
    # The share entry was revoked (row removed / no longer active) - the
    # knowledge_ids projection may still contain the space, but there is no
    # active entry to map back to: the hit is dropped, never leaked.
    resolver, _, _ = default_mapping_fixture(entries=[])

    mapped = await resolver.map_and_authorize_hits(make_scope(space_ids=(10,)), [hit()])

    assert mapped == []


async def test_permission_denied_falls_back_to_next_space_candidate():
    entries = [
        make_entry(100, space_id=10, entry_type=KnowledgeFileEntryType.MANAGER.value),
        make_entry(101, space_id=20, entry_type=KnowledgeFileEntryType.PUBLISH.value),
    ]
    resolver, _, entry_checker = default_mapping_fixture(entries, denied_entries={100})

    mapped = await resolver.map_and_authorize_hits(make_scope(space_ids=(10, 20)), [hit()])

    assert len(mapped) == 1
    assert (int(mapped[0].space_id), int(mapped[0].entry_file_id)) == (20, 101)
    assert entry_checker.calls == [(10, 100), (20, 101)]


async def test_permission_denied_for_all_candidates_drops_hit():
    entries = [
        make_entry(100, space_id=10, entry_type=KnowledgeFileEntryType.MANAGER.value),
    ]
    resolver, _, _ = default_mapping_fixture(entries, denied_entries={100})

    mapped = await resolver.map_and_authorize_hits(make_scope(space_ids=(10,)), [hit()])

    assert mapped == []


async def test_permission_service_unavailable_in_final_check_fails_closed():
    resolver, _, _, _ = make_resolver(
        entries=[make_entry(100, space_id=10, entry_type=KnowledgeFileEntryType.MANAGER.value)],
        documents=[make_document()],
        entry_error=RuntimeError("openfga down"),
    )

    with pytest.raises(SharedStorageContractError) as exc_info:
        await resolver.map_and_authorize_hits(make_scope(space_ids=(10,)), [hit()])
    assert exc_info.value.code == SharedStorageErrorCode.PERMISSION_SERVICE_UNAVAILABLE


async def test_primary_version_switch_drops_stale_version_hits():
    entries = [
        make_entry(100, space_id=10, entry_type=KnowledgeFileEntryType.MANAGER.value),
    ]
    documents = [make_document(primary_version_id=V2)]
    resolver, _, _ = default_mapping_fixture(entries, documents=documents)

    mapped = await resolver.map_and_authorize_hits(
        make_scope(space_ids=(10,)),
        [hit(version_id=V1, chunk_index=0), hit(version_id=V2, chunk_index=0)],
    )

    assert len(mapped) == 1
    assert int(mapped[0].canonical_version_id) == V2


async def test_soft_deleted_document_drops_hits():
    entries = [
        make_entry(100, space_id=10, entry_type=KnowledgeFileEntryType.MANAGER.value),
    ]
    documents = [make_document(lifecycle=KnowledgeDocumentLifecycleStatus.DELETING.value)]
    resolver, _, _ = default_mapping_fixture(entries, documents=documents)

    assert await resolver.map_and_authorize_hits(make_scope(space_ids=(10,)), [hit()]) == []


async def test_projection_pending_fails_closed():
    entries = [
        make_entry(
            100,
            space_id=10,
            entry_type=KnowledgeFileEntryType.MANAGER.value,
            projection=KnowledgeFileProjectionStatus.PENDING.value,
        ),
    ]
    resolver, _, _ = default_mapping_fixture(entries)

    with pytest.raises(SharedStorageContractError) as exc_info:
        await resolver.map_and_authorize_hits(make_scope(space_ids=(10,)), [hit()])
    assert exc_info.value.code == SharedStorageErrorCode.MEMBERSHIP_PROJECTION_NOT_READY


async def test_content_generation_lag_fails_closed():
    entries = [
        make_entry(
            100,
            space_id=10,
            entry_type=KnowledgeFileEntryType.MANAGER.value,
            desired_content=2,
            applied_content=1,
        ),
    ]
    resolver, _, _ = default_mapping_fixture(entries)

    with pytest.raises(SharedStorageContractError) as exc_info:
        await resolver.map_and_authorize_hits(make_scope(space_ids=(10,)), [hit()])
    assert exc_info.value.code == SharedStorageErrorCode.CONTENT_PROJECTION_NOT_READY


async def test_entry_generation_lag_fails_closed():
    entries = [
        make_entry(
            100,
            space_id=10,
            entry_type=KnowledgeFileEntryType.MANAGER.value,
            desired_entry=2,
            applied_entry=1,
        ),
    ]
    resolver, _, _ = default_mapping_fixture(entries)

    with pytest.raises(SharedStorageContractError) as exc_info:
        await resolver.map_and_authorize_hits(make_scope(space_ids=(10,)), [hit()])
    assert exc_info.value.code == SharedStorageErrorCode.MEMBERSHIP_PROJECTION_NOT_READY


async def test_cross_tenant_document_rows_are_ignored():
    entries = [
        make_entry(100, space_id=10, entry_type=KnowledgeFileEntryType.MANAGER.value),
    ]
    documents = [
        make_document(tenant_id=99),  # different tenant row with the same id
    ]
    resolver, _, _ = default_mapping_fixture(entries, documents=documents)

    assert await resolver.map_and_authorize_hits(make_scope(space_ids=(10,)), [hit()]) == []


async def test_folder_move_keeps_mapping():
    entries = [
        make_entry(
            100,
            space_id=10,
            entry_type=KnowledgeFileEntryType.MANAGER.value,
            file_level_path="/moved/folder",
        ),
    ]
    resolver, _, _ = default_mapping_fixture(entries)

    mapped = await resolver.map_and_authorize_hits(make_scope(space_ids=(10,)), [hit()])

    assert len(mapped) == 1
    assert (int(mapped[0].space_id), int(mapped[0].entry_file_id)) == (10, 100)


async def test_same_chunk_deduplicated_across_duplicate_hits():
    entries = [
        make_entry(100, space_id=10, entry_type=KnowledgeFileEntryType.MANAGER.value),
    ]
    resolver, _, _ = default_mapping_fixture(entries)

    mapped = await resolver.map_and_authorize_hits(
        make_scope(space_ids=(10,)),
        [hit(chunk_index=0, score=0.9), hit(chunk_index=0, score=0.8), hit(chunk_index=1, score=0.7)],
    )

    assert [(int(m.chunk_index), m.score) for m in mapped] == [(0, 0.9), (1, 0.7)]


async def test_output_contains_only_mapped_entry_fields():
    entries = [
        make_entry(100, space_id=10, entry_type=KnowledgeFileEntryType.MANAGER.value),
    ]
    resolver, _, _ = default_mapping_fixture(entries)

    mapped = await resolver.map_and_authorize_hits(
        make_scope(space_ids=(10,)), [hit(text="secret knowledge_ids=[1,2,3]")]
    )

    assert len(mapped) == 1
    assert type(mapped[0]) is MappedEntryHit
    field_names = {f for f in mapped[0].__dataclass_fields__}
    assert "knowledge_ids" not in field_names
    assert "raw_chunk_metadata" not in field_names
    assert mapped[0].text == "secret knowledge_ids=[1,2,3]"  # text passthrough only


# ---------------------------------------------------------------------------
# F3.4 over-fetch refill
# ---------------------------------------------------------------------------
class PageStore:
    """Shared-store stub returning pages in score order."""

    def __init__(self, hits: list[CanonicalChunkHit]):
        self.hits = list(hits)
        self.calls: list[tuple[int, int]] = []

    async def __call__(self, query_filter, offset, limit):
        self.calls.append((offset, limit))
        return self.hits[offset : offset + limit]


def _store_hits(count: int, *, document_ids: list[int]) -> list[CanonicalChunkHit]:
    hits = []
    chunk = 0
    while len(hits) < count:
        for document_id in document_ids:
            hits.append(hit(document_id=document_id, chunk_index=chunk, score=1.0 - len(hits) / 100))
            if len(hits) >= count:
                break
        chunk += 1
    return hits


async def test_overfetch_refills_topk_despite_dirty_members():
    # Doc 91's entry is denied (revoked share): every doc-91 hit is dirty and
    # consumes a Top-K slot. Doc 92 fills the result via over-fetch pages.
    entries = [
        make_entry(100, space_id=10, entry_type=KnowledgeFileEntryType.MANAGER.value, document_id=91),
        make_entry(200, space_id=10, entry_type=KnowledgeFileEntryType.PUBLISH.value, document_id=92),
    ]
    documents = [make_document(91, space_id=10), make_document(92, space_id=10)]
    resolver, _, _ = default_mapping_fixture(
        entries, documents=documents, denied_entries={100}
    )

    store_hits = _store_hits(12, document_ids=[91, 91, 92])
    store = PageStore(store_hits)

    mapped = await resolver.map_and_authorize_with_overfetch(
        make_scope(space_ids=(10,)),
        top_k=3,
        fetch_hits=store,
    )

    assert len(mapped) == 3  # recall does not shrink because of dirty members
    assert {int(m.canonical_document_id) for m in mapped} == {92}
    assert store.calls[0] == (0, 6)  # default K x 2 over-fetch
    assert len(store.calls) >= 2  # refill iterations happened


async def test_overfetch_stops_when_store_exhausted():
    entries = [
        make_entry(100, space_id=10, entry_type=KnowledgeFileEntryType.MANAGER.value),
    ]
    resolver, _, _ = default_mapping_fixture(entries)

    store = PageStore([hit(chunk_index=0), hit(chunk_index=1)])

    mapped = await resolver.map_and_authorize_with_overfetch(
        make_scope(space_ids=(10,)),
        top_k=5,
        fetch_hits=store,
    )

    assert len(mapped) == 2  # all remaining candidates, no infinite loop
    assert store.calls == [(0, 10)]


async def test_overfetch_respects_max_rounds():
    entries = [
        make_entry(100, space_id=10, entry_type=KnowledgeFileEntryType.MANAGER.value),
    ]
    settings = RetrievalScopeResolverSettings(
        enabled=True, routing_version=1, overfetch_factor=1, max_overfetch_rounds=1
    )
    resolver, _, _, _ = make_resolver(entries=entries, documents=[make_document()], settings=settings)

    store = PageStore(_store_hits(50, document_ids=[91]))

    mapped = await resolver.map_and_authorize_with_overfetch(
        make_scope(space_ids=(10,)),
        top_k=5,
        fetch_hits=store,
    )

    assert len(store.calls) == 1
    assert len(mapped) == 5  # first page already enough at factor 1


# ---------------------------------------------------------------------------
# explicit canonical constraints (spec 3.5 rule 2)
# ---------------------------------------------------------------------------
async def test_resolve_explicit_canonical_constraints_pins_primary_version():
    entries = [
        make_entry(101, space_id=10, entry_type=KnowledgeFileEntryType.PUBLISH.value),
        make_entry(300, space_id=20, entry_type=None, document_id=None),
    ]
    versions = [
        KnowledgeDocumentVersion(
            id=V1,
            document_id=DOC,
            knowledge_file_id=100,
            version_no=1,
            is_primary=True,
        ),
        KnowledgeDocumentVersion(
            id=V2,
            document_id=92,
            knowledge_file_id=300,
            version_no=1,
            is_primary=True,
        ),
    ]
    documents = [
        make_document(DOC, space_id=20, primary_version_id=V1),
        make_document(92, space_id=20, primary_version_id=V2),
    ]
    resolver, _, _, _ = make_resolver(entries=entries, documents=documents, versions=versions)

    scope = make_scope(space_ids=(10, 20), explicit={10: (101,), 20: (300,)})
    doc_ids, version_ids = await resolver.resolve_explicit_canonical_constraints(scope)

    assert tuple(int(d) for d in doc_ids) == (91, 92)
    assert tuple(int(v) for v in version_ids) == (V1, V2)


async def test_resolve_explicit_canonical_constraints_whole_space_returns_none():
    resolver, _, _, _ = make_resolver()

    assert await resolver.resolve_explicit_canonical_constraints(make_scope()) == (None, None)


async def test_resolve_explicit_canonical_constraints_unresolvable_fails_closed():
    resolver, _, _, _ = make_resolver(entries=[])

    scope = make_scope(space_ids=(10,), explicit={10: (101,)})
    with pytest.raises(SharedStorageContractError) as exc_info:
        await resolver.resolve_explicit_canonical_constraints(scope)
    assert exc_info.value.code == SharedStorageErrorCode.ENTRY_REF_NOT_RESOLVABLE


# ---------------------------------------------------------------------------
# repository batch query (SQL implementation)
# ---------------------------------------------------------------------------
async def test_find_active_entries_for_documents_impl(async_db_session: AsyncSession):
    repo = KnowledgeFileRepositoryImpl(async_db_session)
    async_db_session.add_all(
        [
            make_entry(1, space_id=10, entry_type=KnowledgeFileEntryType.MANAGER.value),
            make_entry(2, space_id=10, entry_type=KnowledgeFileEntryType.SHARE.value, tenant_id=99),
            make_entry(
                3,
                space_id=10,
                entry_type=KnowledgeFileEntryType.PUBLISH.value,
                status=KnowledgeFileEntryStatus.DELETING.value,
            ),
            make_entry(4, space_id=30, entry_type=KnowledgeFileEntryType.PUBLISH.value),
            make_entry(5, space_id=10, entry_type="projection_tombstone"),
        ]
    )
    await async_db_session.commit()

    rows = await repo.find_active_entries_for_documents(
        tenant_id=TENANT,
        document_ids=[DOC],
        knowledge_ids=[10, 20],
    )

    assert [int(r.id) for r in rows] == [1]
