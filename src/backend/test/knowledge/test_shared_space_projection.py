"""F2 content/membership dual-projection tests (spec 3.4 / 3.7 / 4.3).

All storage interaction goes through the frozen-contract fake
``FakeSharedSpaceStorageWriter`` - no Milvus/ES/F1 dependency. The legacy
lease/CAS/retry machinery is exercised through the real projection service
over the async SQLite fixtures.
"""
from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.contracts.identifiers import (
    CanonicalDocumentId,
    TenantId,
)
from bisheng.knowledge.domain.models.knowledge_document import (
    KnowledgeDocument,
)
from bisheng.knowledge.domain.models.knowledge_document_version import (
    KnowledgeDocumentVersion,
)
from bisheng.knowledge.domain.models.knowledge_file import (
    KnowledgeFile,
    KnowledgeFileEntryStatus,
    KnowledgeFileEntryType,
    KnowledgeFileProjectionStatus,
    KnowledgeFileStatus,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_repository_impl import (
    KnowledgeDocumentRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (
    KnowledgeDocumentVersionRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)
from bisheng.knowledge.domain.services.knowledge_document_projection_service import (
    KnowledgeDocumentProjectionService,
)
from bisheng.knowledge.domain.services.knowledge_projection_readiness_service import (
    KnowledgeProjectionReadinessService,
)
from bisheng.knowledge.domain.services.knowledge_version_service import (
    KnowledgeVersionService,
)
from bisheng.knowledge.domain.services.shared_space_projection_support import (
    aggregate_active_knowledge_ids,
    load_shared_content_chunks_from_legacy,
    resolve_shared_space_storage_enabled,
)
from test.fakes.shared_storage_fakes import FakeSharedSpaceStorageWriter

TENANT = 7
DOCUMENT_ID = 91
PRIMARY_VERSION_ID = 910
CONTENT_FILE_ID = 100


def _entry(
    entry_id: int,
    space_id: int,
    entry_type: KnowledgeFileEntryType,
    *,
    entry_status: KnowledgeFileEntryStatus = KnowledgeFileEntryStatus.ACTIVE,
    desired_content_generation: int = 4,
    applied_content_generation: int = 0,
    desired_entry_generation: int = 1,
    applied_entry_generation: int = 0,
    projection_status: KnowledgeFileProjectionStatus = (
        KnowledgeFileProjectionStatus.PENDING
    ),
    **overrides,
) -> KnowledgeFile:
    kwargs = dict(
        id=entry_id,
        tenant_id=TENANT,
        knowledge_id=space_id,
        file_name="manager.pdf",
        status=KnowledgeFileStatus.SUCCESS.value,
        reference_document_id=DOCUMENT_ID,
        entry_type=entry_type.value,
        entry_status=entry_status.value,
        desired_content_generation=desired_content_generation,
        applied_content_generation=applied_content_generation,
        desired_entry_generation=desired_entry_generation,
        applied_entry_generation=applied_entry_generation,
        projection_status=projection_status.value,
    )
    kwargs.update(overrides)
    return KnowledgeFile(**kwargs)


async def _seed_shared_world(session: AsyncSession) -> None:
    """Manager(20) + publish(10) + share(30) around one canonical document."""
    session.add(
        KnowledgeDocument(
            id=DOCUMENT_ID,
            tenant_id=TENANT,
            knowledge_id=20,
            primary_version_id=PRIMARY_VERSION_ID,
            content_generation=4,
        )
    )
    session.add(
        KnowledgeDocumentVersion(
            id=PRIMARY_VERSION_ID,
            document_id=DOCUMENT_ID,
            knowledge_file_id=CONTENT_FILE_ID,
            version_no=1,
            is_primary=True,
        )
    )
    session.add_all(
        [
            _entry(
                100,
                20,
                KnowledgeFileEntryType.MANAGER,
            ),
            _entry(
                101,
                10,
                KnowledgeFileEntryType.PUBLISH,
                projection_previous_file_id=100,
            ),
            _entry(102, 30, KnowledgeFileEntryType.SHARE),
        ]
    )
    await session.commit()


def _chunk_loader(chunks=None):
    loaded: list[int] = []

    async def loader(content_file: KnowledgeFile):
        loaded.append(int(content_file.id))
        return chunks or []

    loader.loaded = loaded  # type: ignore[attr-defined]
    return loader


def _two_chunks():
    from bisheng.knowledge.domain.contracts.shared_space_storage import (
        SharedContentChunk,
    )

    return [
        SharedContentChunk(chunk_index=0, text="chunk zero"),
        SharedContentChunk(chunk_index=1, text="chunk one"),
    ]


def _service(
    session: AsyncSession,
    writer: FakeSharedSpaceStorageWriter,
    *,
    enabled: bool = True,
    chunk_loader=None,
    legacy_writer=None,
    cleaner=None,
) -> KnowledgeDocumentProjectionService:
    return KnowledgeDocumentProjectionService(
        session=session,
        file_repository=KnowledgeFileRepositoryImpl(session),
        document_repository=KnowledgeDocumentRepositoryImpl(session),
        version_repository=KnowledgeDocumentVersionRepositoryImpl(session),
        projection_writer=legacy_writer or AsyncMock(),
        projection_cleaner=cleaner or AsyncMock(),
        shared_storage_writer=writer,
        shared_storage_enabled=enabled,
        shared_content_chunk_loader=chunk_loader,
        shared_embedding_model_id="4",
        lease_seconds=30,
        max_retry_seconds=60,
    )


# ---------------------------------------------------------------------------
# F2.2 aggregation (pure re-aggregation, spec 3.4)
# ---------------------------------------------------------------------------


class TestActiveKnowledgeIdsAggregation:
    def test_aggregates_manager_publish_share_sorted_and_deduped(self):
        entries = [
            _entry(100, 20, KnowledgeFileEntryType.MANAGER),
            _entry(101, 10, KnowledgeFileEntryType.PUBLISH),
            _entry(102, 30, KnowledgeFileEntryType.SHARE),
            # same space twice (manager + share) must dedupe
            _entry(103, 30, KnowledgeFileEntryType.SHARE),
        ]
        assert aggregate_active_knowledge_ids(entries) == (10, 20, 30)

    def test_ignores_non_active_and_non_membership_entries(self):
        entries = [
            _entry(
                100,
                20,
                KnowledgeFileEntryType.MANAGER,
                entry_status=KnowledgeFileEntryStatus.DELETING,
            ),
            _entry(
                104,
                50,
                KnowledgeFileEntryType.PROJECTION_TOMBSTONE,
            ),
            _entry(
                105,
                60,
                KnowledgeFileEntryType.SHARE,
                entry_status=KnowledgeFileEntryStatus.PREPARING,
            ),
            _entry(101, 10, KnowledgeFileEntryType.PUBLISH),
        ]
        assert aggregate_active_knowledge_ids(entries) == (10,)

    def test_empty_when_no_active_entry_remains(self):
        entries = [
            _entry(
                100,
                20,
                KnowledgeFileEntryType.MANAGER,
                entry_status=KnowledgeFileEntryStatus.DELETING,
            )
        ]
        assert aggregate_active_knowledge_ids(entries) == ()


async def test_chunk_loader_falls_back_to_original_space_after_publish_move():
    content_file = KnowledgeFile(
        id=100,
        tenant_id=TENANT,
        knowledge_id=20,
        original_knowledge_id=10,
        file_name="doc.pdf",
    )
    legacy_fields = [
        SimpleNamespace(name=name)
        for name in ("pk", "document_id", "text", "vector")
    ]
    current_collection = SimpleNamespace(
        schema=SimpleNamespace(
            fields=[
                SimpleNamespace(name=name)
                for name in ("pk", "canonical_document_id", "text", "vector")
            ]
        ),
        query=lambda **_kwargs: pytest.fail("shared collection must be skipped"),
    )
    original_collection = SimpleNamespace(
        schema=SimpleNamespace(fields=legacy_fields),
        query=lambda **_kwargs: [
            {
                "pk": 1,
                "document_id": 100,
                "text": "from original",
                "vector": [0.1, 0.2],
            }
        ],
    )
    spaces = {
        20: SimpleNamespace(id=20),
        10: SimpleNamespace(id=10),
    }

    def vector_store(_user_id, *, knowledge):
        collection = (
            current_collection
            if knowledge.id == 20
            else original_collection
        )
        return SimpleNamespace(col=collection)

    with (
        patch(
            "bisheng.knowledge.domain.models.knowledge.KnowledgeDao.aquery_by_id",
            new=AsyncMock(side_effect=lambda space_id: spaces.get(space_id)),
        ),
        patch(
            "bisheng.knowledge.domain.knowledge_rag.KnowledgeRag."
            "init_knowledge_milvus_vectorstore_sync",
            side_effect=vector_store,
        ),
    ):
        chunks = await load_shared_content_chunks_from_legacy(content_file)

    assert len(chunks) == 1
    assert chunks[0].text == "from original"
    assert chunks[0].vector == [0.1, 0.2]


async def test_content_generation_requeue_resets_exhausted_retry_state(
    async_db_session: AsyncSession,
):
    await _seed_shared_world(async_db_session)
    repository = KnowledgeFileRepositoryImpl(async_db_session)
    entry = await repository.find_by_id(100)
    entry.projection_status = KnowledgeFileProjectionStatus.FAILED.value
    entry.projection_retry_count = 8
    entry.projection_last_error = "retry_exhausted:test"
    async_db_session.add(entry)
    await async_db_session.commit()

    assert await repository.mark_document_entries_content_generation(
        DOCUMENT_ID, 5
    ) == 3
    await async_db_session.commit()

    entry = await repository.find_by_id(100)
    assert entry.projection_status == KnowledgeFileProjectionStatus.PENDING.value
    assert entry.projection_retry_count == 0
    assert entry.projection_last_error is None


# ---------------------------------------------------------------------------
# F2.1/F2.4/F2.5 content + membership projection through the real service
# ---------------------------------------------------------------------------


class TestSharedDualProjection:
    async def test_first_convergence_upserts_content_then_membership(
        self, async_db_session: AsyncSession
    ):
        await _seed_shared_world(async_db_session)
        writer = FakeSharedSpaceStorageWriter()
        loader = _chunk_loader(_two_chunks())
        service = _service(async_db_session, writer, chunk_loader=loader)

        result = await service.process_entry(
            tenant_id=TENANT,
            entry_id=100,
            lease_owner="worker-a",
        )

        assert result.status == "ready"
        assert writer.calls == ["upsert_content", "update_membership"]
        # membership array is the full active-entry aggregation
        assert writer.membership_of(TENANT, DOCUMENT_ID) == (10, 20, 30)
        # content was written once, for the primary version + generation
        assert list(writer.content) == [
            (TENANT, DOCUMENT_ID, PRIMARY_VERSION_ID, 4)
        ]
        assert writer.chunk_count(TENANT, DOCUMENT_ID) == 2
        # loader touched the primary physical file only
        assert loader.loaded == [CONTENT_FILE_ID]

    async def test_later_entries_rewrite_membership_only(
        self, async_db_session: AsyncSession
    ):
        await _seed_shared_world(async_db_session)
        writer = FakeSharedSpaceStorageWriter()
        loader = _chunk_loader(_two_chunks())
        service = _service(async_db_session, writer, chunk_loader=loader)

        await service.process_entry(
            tenant_id=TENANT, entry_id=100, lease_owner="w1"
        )
        assert writer.calls == ["upsert_content", "update_membership"]

        writer.calls.clear()
        loader.loaded.clear()
        # publish entry converges: single-copy invariant => no content rewrite,
        # and no copy_vector / legacy projection writer call (F2.5).
        legacy_writer = AsyncMock()
        service.projection_writer = legacy_writer
        result = await service.process_entry(
            tenant_id=TENANT, entry_id=101, lease_owner="w2"
        )

        assert result.status == "ready"
        assert writer.calls == ["update_membership"]
        assert loader.loaded == []
        legacy_writer.assert_not_awaited()

    async def test_share_withdraw_reaggregates_membership_without_content(
        self, async_db_session: AsyncSession
    ):
        await _seed_shared_world(async_db_session)
        repository = KnowledgeFileRepositoryImpl(async_db_session)
        for entry_id in (100, 101):
            entry = await repository.find_by_id(entry_id)
            entry.applied_content_generation = 4
            entry.applied_entry_generation = 1
            entry.projection_status = (
                KnowledgeFileProjectionStatus.READY.value
            )
            async_db_session.add(entry)
        share = await repository.find_by_id(102)
        share.entry_status = KnowledgeFileEntryStatus.DELETING.value
        share.desired_entry_generation = 2
        async_db_session.add(share)
        await async_db_session.commit()

        writer = FakeSharedSpaceStorageWriter()
        loader = _chunk_loader(_two_chunks())
        service = _service(async_db_session, writer, chunk_loader=loader)

        result = await service.process_entry(
            tenant_id=TENANT, entry_id=102, lease_owner="w3"
        )

        assert result.status == "cleaned"
        # share space 30 removed by re-aggregation, content untouched
        assert writer.calls == ["update_membership"]
        assert writer.membership_of(TENANT, DOCUMENT_ID) == (10, 20)
        assert loader.loaded == []

    async def test_membership_generation_carries_entry_generation(
        self, async_db_session: AsyncSession
    ):
        await _seed_shared_world(async_db_session)
        writer = FakeSharedSpaceStorageWriter()
        loader = _chunk_loader(_two_chunks())
        captured: list = []

        original = writer.update_membership

        async def spy(request):
            captured.append(request)
            return await original(request)

        writer.update_membership = spy  # type: ignore[method-assign]
        service = _service(async_db_session, writer, chunk_loader=loader)

        await service.process_entry(
            tenant_id=TENANT, entry_id=100, lease_owner="w4"
        )

        assert len(captured) == 1
        # document-level monotonic membership generation: max(content gen 4,
        # active desired entry gens 1) - never regresses below a snapshot the
        # writer already applied
        assert captured[0].membership_generation == 4
        assert captured[0].content_generation == 4
        assert captured[0].knowledge_ids == (10, 20, 30)


# ---------------------------------------------------------------------------
# F2.3 empty aggregation short-circuits to the tombstone flow
# ---------------------------------------------------------------------------


class TestEmptyAggregationTombstone:
    async def test_last_active_entry_removed_deletes_content(
        self, async_db_session: AsyncSession
    ):
        await _seed_shared_world(async_db_session)
        repository = KnowledgeFileRepositoryImpl(async_db_session)
        for entry_id in (100, 101, 102):
            entry = await repository.find_by_id(entry_id)
            entry.entry_status = KnowledgeFileEntryStatus.DELETING.value
            entry.projection_status = (
                KnowledgeFileProjectionStatus.PENDING.value
            )
            async_db_session.add(entry)
        await async_db_session.commit()

        writer = FakeSharedSpaceStorageWriter()
        loader = _chunk_loader(_two_chunks())
        # pre-existing content that the tombstone must remove
        writer.calls.clear()
        service = _service(async_db_session, writer, chunk_loader=loader)

        result = await service.process_entry(
            tenant_id=TENANT, entry_id=100, lease_owner="w5"
        )

        # delete only: no empty-array membership write, no retryable error -
        # the lease/CAS apply converges the entry to ready.
        assert result.status == "cleaned"
        assert writer.calls == ["delete_content"]
        entry = await repository.find_by_id(100)
        assert entry.projection_status == (
            KnowledgeFileProjectionStatus.READY.value
        )
        assert entry.projection_retry_count == 0

    async def test_empty_aggregation_never_raises_empty_membership(
        self, async_db_session: AsyncSession
    ):
        await _seed_shared_world(async_db_session)
        repository = KnowledgeFileRepositoryImpl(async_db_session)
        manager = await repository.find_by_id(100)
        manager.entry_status = KnowledgeFileEntryStatus.DELETING.value
        share = await repository.find_by_id(102)
        share.entry_status = KnowledgeFileEntryStatus.DELETING.value
        publish = await repository.find_by_id(101)
        publish.entry_status = KnowledgeFileEntryStatus.INVALID.value
        async_db_session.add_all([manager, share, publish])
        await async_db_session.commit()

        writer = FakeSharedSpaceStorageWriter()
        service = _service(
            async_db_session, writer, chunk_loader=_chunk_loader(_two_chunks())
        )

        result = await service.process_entry(
            tenant_id=TENANT, entry_id=102, lease_owner="w6"
        )
        assert result.status == "cleaned"
        assert writer.calls == ["delete_content"]


# ---------------------------------------------------------------------------
# F2 gating: default off keeps the legacy projection path untouched
# ---------------------------------------------------------------------------


class TestLegacyGating:
    async def test_shared_writer_ignored_when_switch_off(
        self, async_db_session: AsyncSession
    ):
        await _seed_shared_world(async_db_session)
        writer = FakeSharedSpaceStorageWriter()
        legacy_writer = AsyncMock()
        service = _service(
            async_db_session,
            writer,
            enabled=False,
            legacy_writer=legacy_writer,
        )

        result = await service.process_entry(
            tenant_id=TENANT, entry_id=101, lease_owner="w7"
        )

        assert result.status == "ready"
        assert writer.calls == []
        legacy_writer.assert_awaited_once()

    async def test_config_resolution_defaults_to_disabled(self):
        assert await resolve_shared_space_storage_enabled() is False

    async def test_config_resolution_reads_top_level_shared_storage_block(self):
        settings = SimpleNamespace(
            knowledge_space_shared_storage=SimpleNamespace(enabled=True)
        )
        config_module = sys.modules[
            "bisheng.common.services.config_service"
        ]
        with patch.object(config_module, "settings", settings):
            assert await resolve_shared_space_storage_enabled() is True


# ---------------------------------------------------------------------------
# F2.7 readiness: content ready AND membership ready AND entry on primary
# ---------------------------------------------------------------------------


def _readiness_service(session: AsyncSession) -> (
    KnowledgeProjectionReadinessService
):
    return KnowledgeProjectionReadinessService(
        file_repository=KnowledgeFileRepositoryImpl(session),
        document_repository=KnowledgeDocumentRepositoryImpl(session),
    )


def _ready(seeded=None):
    return dict(
        desired_content_generation=4,
        applied_content_generation=4,
        desired_entry_generation=1,
        applied_entry_generation=1,
        projection_status=KnowledgeFileProjectionStatus.READY,
    )


class TestProjectionReadiness:
    async def _seed_converged(self, session: AsyncSession):
        session.add(
            KnowledgeDocument(
                id=DOCUMENT_ID,
                tenant_id=TENANT,
                knowledge_id=20,
                primary_version_id=PRIMARY_VERSION_ID,
                content_generation=4,
            )
        )
        session.add_all(
            [
                _entry(
                    100,
                    20,
                    KnowledgeFileEntryType.MANAGER,
                    **_ready(),
                ),
                _entry(
                    101,
                    10,
                    KnowledgeFileEntryType.PUBLISH,
                    **_ready(),
                ),
            ]
        )
        await session.commit()

    async def test_ready_when_all_three_conditions_hold(
        self, async_db_session: AsyncSession
    ):
        await self._seed_converged(async_db_session)
        result = await _readiness_service(
            async_db_session
        ).get_content_membership_readiness(
            tenant_id=TenantId(TENANT),
            entry_file_id=101,
        )
        assert result.ready is True
        assert result.reason is None

    async def test_content_not_ready_when_generation_lags(
        self, async_db_session: AsyncSession
    ):
        await self._seed_converged(async_db_session)
        repository = KnowledgeFileRepositoryImpl(async_db_session)
        manager = await repository.find_by_id(100)
        manager.applied_content_generation = 3
        async_db_session.add(manager)
        publish = await repository.find_by_id(101)
        publish.applied_content_generation = 3
        async_db_session.add(publish)
        await async_db_session.commit()

        result = await _readiness_service(
            async_db_session
        ).get_content_membership_readiness(
            tenant_id=TenantId(TENANT),
            canonical_document_id=CanonicalDocumentId(DOCUMENT_ID),
        )
        from bisheng.knowledge.domain.contracts.errors import (
            SharedStorageErrorCode,
        )

        assert result.ready is False
        assert result.reason == (
            SharedStorageErrorCode.CONTENT_PROJECTION_NOT_READY
        )

    async def test_membership_not_ready_when_entry_generation_lags(
        self, async_db_session: AsyncSession
    ):
        from bisheng.knowledge.domain.contracts.errors import (
            SharedStorageErrorCode,
        )

        await self._seed_converged(async_db_session)
        repository = KnowledgeFileRepositoryImpl(async_db_session)
        publish = await repository.find_by_id(101)
        publish.applied_entry_generation = 0
        async_db_session.add(publish)
        await async_db_session.commit()

        result = await _readiness_service(
            async_db_session
        ).get_content_membership_readiness(
            tenant_id=TenantId(TENANT),
            entry_file_id=101,
        )
        assert result.ready is False
        assert result.reason == (
            SharedStorageErrorCode.MEMBERSHIP_PROJECTION_NOT_READY
        )

    async def test_entry_not_on_primary_when_entry_content_behind(
        self, async_db_session: AsyncSession
    ):
        from bisheng.knowledge.domain.contracts.errors import (
            SharedStorageErrorCode,
        )

        await self._seed_converged(async_db_session)
        repository = KnowledgeFileRepositoryImpl(async_db_session)
        publish = await repository.find_by_id(101)
        publish.applied_content_generation = 3
        async_db_session.add(publish)
        await async_db_session.commit()

        result = await _readiness_service(
            async_db_session
        ).get_content_membership_readiness(
            tenant_id=TenantId(TENANT),
            entry_file_id=101,
        )
        assert result.ready is False
        assert result.reason == (
            SharedStorageErrorCode.ENTRY_NOT_ON_PRIMARY_VERSION
        )

    async def test_entry_not_on_primary_when_version_mismatch(
        self, async_db_session: AsyncSession
    ):
        from bisheng.knowledge.domain.contracts.errors import (
            SharedStorageErrorCode,
        )
        from bisheng.knowledge.domain.contracts.identifiers import (
            CanonicalVersionId,
        )

        await self._seed_converged(async_db_session)
        result = await _readiness_service(
            async_db_session
        ).get_content_membership_readiness(
            tenant_id=TenantId(TENANT),
            canonical_document_id=CanonicalDocumentId(DOCUMENT_ID),
            canonical_version_id=CanonicalVersionId(PRIMARY_VERSION_ID + 1),
        )
        assert result.ready is False
        assert result.reason == (
            SharedStorageErrorCode.ENTRY_NOT_ON_PRIMARY_VERSION
        )

    async def test_entry_not_active_fail_closed(
        self, async_db_session: AsyncSession
    ):
        from bisheng.knowledge.domain.contracts.errors import (
            SharedStorageErrorCode,
        )

        await self._seed_converged(async_db_session)
        repository = KnowledgeFileRepositoryImpl(async_db_session)
        publish = await repository.find_by_id(101)
        publish.entry_status = KnowledgeFileEntryStatus.DELETING.value
        async_db_session.add(publish)
        await async_db_session.commit()

        result = await _readiness_service(
            async_db_session
        ).get_content_membership_readiness(
            tenant_id=TenantId(TENANT),
            entry_file_id=101,
        )
        assert result.ready is False
        assert result.reason == SharedStorageErrorCode.ENTRY_NOT_ACTIVE

    async def test_requires_exactly_one_lookup_key(
        self, async_db_session: AsyncSession
    ):
        import pytest

        readiness = _readiness_service(async_db_session)
        with pytest.raises(ValueError):
            await readiness.get_content_membership_readiness(
                tenant_id=TenantId(TENANT)
            )


# ---------------------------------------------------------------------------
# F2.8 primary switch inheritance
# ---------------------------------------------------------------------------


class TestPrimarySwitchInheritance:
    async def _seed_version_world(self, session: AsyncSession):
        session.add_all(
            [
                KnowledgeDocument(
                    id=DOCUMENT_ID,
                    tenant_id=TENANT,
                    knowledge_id=20,
                    primary_version_id=PRIMARY_VERSION_ID,
                    content_generation=4,
                ),
                KnowledgeDocumentVersion(
                    id=PRIMARY_VERSION_ID,
                    document_id=DOCUMENT_ID,
                    knowledge_file_id=CONTENT_FILE_ID,
                    version_no=1,
                    is_primary=False,
                ),
                KnowledgeDocumentVersion(
                    id=PRIMARY_VERSION_ID + 1,
                    document_id=DOCUMENT_ID,
                    knowledge_file_id=200,
                    version_no=2,
                    is_primary=True,
                ),
                _entry(
                    100,
                    20,
                    KnowledgeFileEntryType.MANAGER,
                    desired_content_generation=4,
                    applied_content_generation=4,
                    desired_entry_generation=1,
                    applied_entry_generation=1,
                    projection_status=KnowledgeFileProjectionStatus.READY,
                ),
                _entry(101, 10, KnowledgeFileEntryType.PUBLISH),
            ]
        )
        await session.commit()

    def _version_service(self, session: AsyncSession) -> (
        KnowledgeVersionService
    ):
        return KnowledgeVersionService(
            request=SimpleNamespace(),
            login_user=SimpleNamespace(
                tenant_id=TENANT, user_id=1, user_name="tester"
            ),
            doc_repo=KnowledgeDocumentRepositoryImpl(session),
            version_repo=KnowledgeDocumentVersionRepositoryImpl(session),
            knowledge_file_repo=KnowledgeFileRepositoryImpl(session),
        )

    async def test_bump_increments_generation_and_reprojects_entries(
        self, async_db_session: AsyncSession
    ):
        await self._seed_version_world(async_db_session)
        service = self._version_service(async_db_session)

        await service._bump_shared_content_generation_for_primary_switch(
            document_id=DOCUMENT_ID,
        )

        document = await KnowledgeDocumentRepositoryImpl(
            async_db_session
        ).find_by_id(DOCUMENT_ID)
        assert document.content_generation == 5

        repository = KnowledgeFileRepositoryImpl(async_db_session)
        manager = await repository.find_by_id(100)
        publish = await repository.find_by_id(101)
        # active entries inherit the new generation and go back to pending so
        # the projection worker rewrites the primary content under the
        # canonical (re-aggregated) knowledge_ids
        for entry in (manager, publish):
            assert entry.desired_content_generation == 5
            assert entry.projection_status == (
                KnowledgeFileProjectionStatus.PENDING.value
            )

    async def test_switch_helper_disabled_without_config(
        self, async_db_session: AsyncSession
    ):
        await self._seed_version_world(async_db_session)
        service = self._version_service(async_db_session)
        assert await service._shared_space_projection_enabled() is False

        document = await KnowledgeDocumentRepositoryImpl(
            async_db_session
        ).find_by_id(DOCUMENT_ID)
        assert document.content_generation == 4
