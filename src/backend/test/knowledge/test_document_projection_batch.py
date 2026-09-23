"""批量投影的查询、归属聚合和失败重试契约。"""

from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.knowledge.domain.services.document_projection_batch_service import run_projection_rounds


def make_writer(**kwargs):
    from bisheng.knowledge.domain.contracts.shared_space_storage import ProjectionContentInspection, SharedContentChunk

    async def inspect(identities, *, guard):
        await guard()
        return {
            identity.canonical_document_id: ProjectionContentInspection(
                "reuse",
                "verified stored content",
                (SharedContentChunk(0, "content", [0.1, 0.2]),),
            )
            for identity in identities
        }

    return SimpleNamespace(
        schema_spec=SimpleNamespace(embedding_model_id=1),
        inspect_projection_content=AsyncMock(side_effect=inspect),
        **kwargs,
    )


@pytest.fixture
async def batch_environment(async_db_engine, monkeypatch):
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
    from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
    from bisheng.knowledge.domain.repositories.implementations import (
        document_projection_batch_repository as repository_module,
    )
    from test.knowledge.test_knowledge_document_projection_service import _seed_entries

    # 本测试验证投影状态事务; 全文 outbox 行为由原模块集成测试覆盖。
    monkeypatch.setattr(repository_module, "request_file_sync_intents", AsyncMock())
    sessions = []

    @asynccontextmanager
    async def factory():
        async with AsyncSession(async_db_engine, expire_on_commit=False) as session:
            sessions.append(session)
            yield repository_module.DocumentProjectionBatchRepository(session)

    async with factory() as repository:
        await _seed_entries(repository.session)
        repository.session.add(
            KnowledgeDocument(id=91, tenant_id=7, knowledge_id=20, content_generation=4, primary_version_id=501)
        )
        repository.session.add(
            KnowledgeDocumentVersion(id=501, document_id=91, knowledge_file_id=100, version_no=1, is_primary=True)
        )
        await repository.session.commit()
    return factory, sessions


async def test_batch_reads_all_memberships_and_settles_together(batch_environment):
    from bisheng.knowledge.domain.services.document_projection_batch_service import DocumentProjectionBatchService

    factory, _sessions = batch_environment
    writer = make_writer(apply_projection_batch=AsyncMock(return_value={}))
    loader = AsyncMock()
    service = DocumentProjectionBatchService(
        repository_factory=factory,
        writer=writer,
        chunk_loader=loader,
        finalizer=AsyncMock(),
    )
    result = await service.run(7, [101, 102], "owner")
    assert result == {101: "ready", 102: "ready"}
    writer.apply_projection_batch.assert_awaited_once()
    plans = writer.apply_projection_batch.await_args.args[0]
    assert len(plans) == 1
    assert plans[0].membership.knowledge_ids == (10, 20, 30)
    assert plans[0].content.chunks[0].vector == [0.1, 0.2]
    loader.assert_not_awaited()
    async with factory() as repository:
        records = await repository.find_by_ids([101, 102])
        assert all(row.projection_status == "ready" and row.projection_lease_owner is None for row in records)
        assert all(row.applied_content_generation == 4 for row in records)


async def test_failure_is_persisted_hidden_from_scanner_and_exhausted(batch_environment):
    from bisheng.knowledge.domain.services.document_projection_batch_service import DocumentProjectionBatchService

    factory, _ = batch_environment
    attempts = []

    async def write(plans, *, guard):
        await guard()
        async with factory() as repository:
            row = await repository.find_by_id(101)
            attempts.append(row.projection_retry_count)
            assert await repository.find_projection_candidates(now=datetime.now(), limit=100, max_retries=4) == []
        return {91: "backend unavailable"}

    writer = make_writer(apply_projection_batch=write)
    service = DocumentProjectionBatchService(
        repository_factory=factory,
        writer=writer,
        chunk_loader=AsyncMock(),
        finalizer=AsyncMock(),
        max_attempts=2,
    )
    result = await service.run(7, [101, 102], "owner")
    assert result == {101: "exhausted", 102: "exhausted"}
    assert attempts == [0, 1]
    async with factory() as repository:
        rows = await repository.find_by_ids([101, 102])
        assert all(row.projection_retry_count == 2 and row.projection_lease_owner is None for row in rows)
        assert all(row.projection_last_error.startswith("retry_exhausted:") for row in rows)
        assert await repository.find_projection_candidates(now=datetime.now(), limit=100, max_retries=2) == []


async def test_version_change_and_foreign_owner_are_not_overwritten(batch_environment):
    factory, _ = batch_environment
    async with factory() as repository:
        snapshot = await repository.claim_batch([101, 102], "first", 4)
    async with factory() as repository:
        row = await repository.find_by_id(101)
        row.desired_content_generation = 5
        other = await repository.find_by_id(102)
        other.projection_lease_owner = "second"
        repository.session.add_all([row, other])
        await repository.session.commit()
    async with factory() as repository:
        with pytest.raises(RuntimeError, match="ownership"):
            await repository.renew("first", [101, 102])
        result = await repository.settle(snapshot.claimed, "first", {}, 4)
        assert result == {101: "stale", 102: "not_claimed"}
    async with factory() as repository:
        row = await repository.find_by_id(101)
        assert row.applied_content_generation == 0 and row.desired_content_generation == 5
        assert (await repository.find_by_id(102)).projection_lease_owner == "second"


async def test_retry_budget_survives_an_interrupted_delivery(batch_environment):
    from bisheng.knowledge.domain.services.document_projection_batch_service import DocumentProjectionBatchService

    factory, _ = batch_environment
    async with factory() as repository:
        context = await repository.claim_batch([101], "first", 2)
        await repository.settle(context.claimed, "first", {101: "first failure"}, 2)
        await repository.release("first")
    writer = make_writer(apply_projection_batch=AsyncMock(return_value={91: "still unavailable"}))
    service = DocumentProjectionBatchService(
        repository_factory=factory,
        writer=writer,
        chunk_loader=AsyncMock(),
        finalizer=AsyncMock(),
        max_attempts=2,
    )
    assert await service.run(7, [101], "second") == {101: "exhausted"}
    writer.apply_projection_batch.assert_awaited_once()


async def test_content_is_prepared_once_for_all_entries_of_one_document(batch_environment):
    from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
    from bisheng.knowledge.domain.services.document_projection_batch_service import DocumentProjectionBatchService

    factory, _ = batch_environment
    async with factory() as repository:
        document = await repository.session.get(KnowledgeDocument, 91)
        document.content_generation = 5
        for row in await repository.find_by_ids([100, 101, 102]):
            row.desired_content_generation = 5
            row.projection_status = "pending"
            repository.session.add(row)
        repository.session.add(document)
        await repository.session.commit()
    from bisheng.knowledge.domain.contracts.shared_space_storage import SharedContentChunk

    loader = AsyncMock(return_value=[SharedContentChunk(0, "content", [0.1, 0.2])])
    writer = make_writer(apply_projection_batch=AsyncMock(return_value={}))
    writer.inspect_projection_content = AsyncMock(
        return_value={
            91: SimpleNamespace(action="rebuild", reason="both stores lack target content", chunks=()),
        }
    )
    service = DocumentProjectionBatchService(
        repository_factory=factory,
        writer=writer,
        chunk_loader=loader,
        finalizer=AsyncMock(),
        batch_size=1,
        allow_content_rebuild=True,
    )
    result = await service.run(7, [101, 102, 100], "owner")
    assert set(result.values()) == {"ready"}
    loader.assert_awaited_once()
    writer.apply_projection_batch.assert_awaited_once()
    plans = writer.apply_projection_batch.await_args.args[0]
    assert len(plans) == 1 and plans[0].content.identity.content_generation == 5


async def test_settlement_rolls_back_if_fulltext_intent_fails(batch_environment, monkeypatch):
    from bisheng.knowledge.domain.repositories.implementations import document_projection_batch_repository as module

    factory, _ = batch_environment
    async with factory() as repository:
        context = await repository.claim_batch([101, 102], "owner", 4)
    monkeypatch.setattr(module, "request_file_sync_intents", AsyncMock(side_effect=RuntimeError("outbox unavailable")))
    with pytest.raises(RuntimeError, match="outbox"):
        async with factory() as repository:
            await repository.settle(context.claimed, "owner", {}, 4)
    async with factory() as repository:
        rows = await repository.find_by_ids([101, 102])
        assert all(row.applied_content_generation == 0 and row.projection_status == "processing" for row in rows)


async def test_cleanup_runs_only_after_batch_state_is_committed(batch_environment):
    from bisheng.knowledge.domain.services.document_projection_batch_service import DocumentProjectionBatchService

    factory, _ = batch_environment
    async with factory() as repository:
        row = await repository.find_by_id(101)
        row.entry_status = "deleting"
        repository.session.add(row)
        await repository.session.commit()

    async def finalize(expected):
        async with factory() as repository:
            row = await repository.find_by_id(expected.id)
            assert row.projection_status == "ready" and row.projection_lease_owner == "owner"
            assert row.applied_content_generation == row.desired_content_generation
            await repository.session.delete(row)
            await repository.session.commit()

    writer = make_writer(apply_projection_batch=AsyncMock(return_value={}))
    service = DocumentProjectionBatchService(
        repository_factory=factory,
        writer=writer,
        chunk_loader=AsyncMock(),
        finalizer=finalize,
    )
    assert await service.run(7, [101, 102], "owner") == {101: "cleaned", 102: "ready"}
    assert writer.apply_projection_batch.await_args.args[0][0].membership.knowledge_ids == (20, 30)


async def test_expired_lease_can_be_recovered_but_not_renewed_by_old_owner(batch_environment):
    from datetime import timedelta

    factory, _ = batch_environment
    async with factory() as repository:
        await repository.claim_batch([101], "old", 4)
        row = await repository.find_by_id(101)
        row.projection_lease_until = datetime.now() - timedelta(seconds=1)
        repository.session.add(row)
        await repository.session.commit()
    async with factory() as repository:
        with pytest.raises(RuntimeError, match="expired"):
            await repository.renew("old")
    async with factory() as repository:
        recovered = await repository.claim_batch([101], "new", 4)
        assert [row.id for row in recovered.claimed] == [101]
        assert recovered.claimed[0].projection_lease_owner == "new"


async def test_retry_starts_after_all_initial_batches_and_has_a_limit():
    calls = []

    async def execute(ids):
        calls.append(list(ids))
        return {entry_id: "failed" if entry_id == 2 else "ready" for entry_id in ids}

    sleep = AsyncMock()
    result = await run_projection_rounds(
        [1, 2, 3, 4, 5],
        execute=execute,
        batch_size=2,
        max_attempts=4,
        sleep=sleep,
    )
    assert calls == [[1, 2], [3, 4], [5], [2], [2], [2]]
    assert result == {1: "ready", 2: "failed", 3: "ready", 4: "ready", 5: "ready"}
    assert sleep.await_count == 3


@pytest.mark.parametrize("ids", [[], [1, 1, 2]])
async def test_empty_and_duplicate_input(ids):
    execute = AsyncMock(side_effect=lambda values: dict.fromkeys(values, "ready"))
    result = await run_projection_rounds(ids, execute=execute, batch_size=2, max_attempts=4, sleep=AsyncMock())
    assert list(result) == sorted(set(ids))
    assert execute.await_count == bool(ids)


async def test_existing_content_is_reused_when_no_entry_is_ready(batch_environment):
    from bisheng.knowledge.domain.contracts.shared_space_storage import SharedContentChunk
    from bisheng.knowledge.domain.services.document_projection_batch_service import DocumentProjectionBatchService

    factory, _ = batch_environment
    async with factory() as repository:
        row = await repository.find_by_id(100)
        row.projection_status = "failed"
        row.status = 3
        repository.session.add(row)
        await repository.session.commit()
    chunks = (SharedContentChunk(chunk_index=0, text="existing content", vector=[0.1, 0.2]),)
    writer = SimpleNamespace(
        schema_spec=SimpleNamespace(embedding_model_id=1),
        inspect_projection_content=AsyncMock(
            return_value={
                91: SimpleNamespace(action="reuse", reason="stored content is valid", chunks=chunks),
            }
        ),
        apply_projection_batch=AsyncMock(return_value={}),
    )
    loader = AsyncMock(side_effect=AssertionError("must not reparse existing content"))
    service = DocumentProjectionBatchService(
        repository_factory=factory,
        writer=writer,
        chunk_loader=loader,
        finalizer=AsyncMock(),
        max_attempts=1,
    )
    result = await service.run(7, [100, 101, 102], "owner")
    assert set(result.values()) == {"ready"}
    loader.assert_not_awaited()
    writer.inspect_projection_content.assert_awaited_once()
    assert writer.apply_projection_batch.await_args.args[0][0].content.chunks == chunks


@pytest.mark.parametrize(
    ("action", "file_status", "outcome"),
    [
        ("query_error", 2, "exhausted"),
        ("defer", 2, "exhausted"),
        ("rebuild", 1, "exhausted"),
        ("rebuild", 3, "exhausted"),
        ("embed", 2, "ready"),
    ],
)
async def test_recovery_does_not_parse_on_unknown_content_or_busy_file(
    batch_environment,
    action,
    file_status,
    outcome,
):
    from bisheng.knowledge.domain.contracts.shared_space_storage import ProjectionContentInspection, SharedContentChunk
    from bisheng.knowledge.domain.services.document_projection_batch_service import DocumentProjectionBatchService

    factory, _ = batch_environment
    async with factory() as repository:
        row = await repository.find_by_id(100)
        row.status = file_status
        repository.session.add(row)
        await repository.session.commit()
    writer = make_writer(apply_projection_batch=AsyncMock(return_value={}))
    writer.inspect_projection_content = AsyncMock(
        side_effect=TimeoutError("ES timeout") if action == "query_error" else None,
        return_value={91: ProjectionContentInspection(action, "probe evidence", (SharedContentChunk(0, "正文"),))},
    )
    loader = AsyncMock(side_effect=AssertionError("original file parsing is forbidden"))
    embedder = AsyncMock(return_value=(SharedContentChunk(0, "正文", [0.1, 0.2]),))
    service = DocumentProjectionBatchService(
        repository_factory=factory,
        writer=writer,
        chunk_loader=loader,
        chunk_embedder=embedder,
        finalizer=AsyncMock(),
        max_attempts=1,
        allow_content_rebuild=True,
    )
    assert await service.run(7, [101], "owner") == {101: outcome}
    loader.assert_not_awaited()
    if action == "embed":
        embedder.assert_awaited_once()
        assert writer.apply_projection_batch.await_args.args[0][0].content.chunks[0].text == "正文"
    else:
        embedder.assert_not_awaited()
        writer.apply_projection_batch.assert_not_awaited()


async def test_retry_rejects_identical_but_truncated_store_prefixes(batch_environment):
    from bisheng.knowledge.domain.contracts.shared_space_storage import ProjectionContentInspection, SharedContentChunk
    from bisheng.knowledge.domain.services.document_projection_batch_service import DocumentProjectionBatchService

    factory, _ = batch_environment
    chunks = (SharedContentChunk(0, "第一块", [0.1, 0.2]), SharedContentChunk(1, "第二块", [0.3, 0.4]))
    writer = make_writer(apply_projection_batch=AsyncMock(side_effect=[{91: "second page failed"}, {}]))
    writer.inspect_projection_content = AsyncMock(
        side_effect=[
            {91: ProjectionContentInspection("rebuild", "both stores empty")},
            {91: ProjectionContentInspection("reuse", "both stores have first chunk", chunks[:1])},
        ]
    )
    loader = AsyncMock(return_value=chunks)
    service = DocumentProjectionBatchService(
        repository_factory=factory,
        writer=writer,
        chunk_loader=loader,
        finalizer=AsyncMock(),
        max_attempts=2,
        allow_content_rebuild=True,
    )
    assert await service.run(7, [101], "owner") == {101: "ready"}
    assert loader.await_count == 2
    assert len(writer.apply_projection_batch.await_args.args[0][0].content.chunks) == 2


@pytest.mark.parametrize("action", ["rebuild", "embed"])
async def test_default_projection_hands_content_work_to_parse_worker(batch_environment, action):
    from bisheng.knowledge.domain.contracts.shared_space_storage import ProjectionContentInspection, SharedContentChunk
    from bisheng.knowledge.domain.services.document_projection_batch_service import DocumentProjectionBatchService

    factory, _ = batch_environment
    async with factory() as repository:
        row = await repository.find_by_id(102)
        row.entry_status = "invalid"
        repository.session.add(row)
        await repository.session.commit()
    writer = make_writer(apply_projection_batch=AsyncMock(return_value={}))
    writer.inspect_projection_content = AsyncMock(
        return_value={
            91: ProjectionContentInspection(action, "recovery required", (SharedContentChunk(0, "正文"),)),
        }
    )
    loader = AsyncMock(side_effect=AssertionError("default worker must not parse"))
    embedder = AsyncMock(side_effect=AssertionError("default worker must not embed"))
    finalizer = AsyncMock()
    deliveries = []

    async def dispatch(tenant_id, entry_ids, reservation):
        async with factory() as repository:
            rows = await repository.find_by_ids(entry_ids)
            assert all(row.projection_status == "pending" for row in rows)
            assert all(row.projection_lease_owner == reservation for row in rows)
            assert all(row.applied_content_generation == 0 for row in rows)
        deliveries.append((tenant_id, entry_ids, reservation))

    service = DocumentProjectionBatchService(
        repository_factory=factory,
        writer=writer,
        chunk_loader=loader,
        chunk_embedder=embedder,
        finalizer=finalizer,
        max_attempts=1,
    )
    service.rebuild_dispatch = dispatch
    assert await service.run(7, [101, 102], "default-owner") == {101: "rebuild_queued", 102: "rebuild_queued"}
    assert len(deliveries) == 1 and deliveries[0][:2] == (7, [101, 102])
    finalizer.assert_not_awaited()
    loader.assert_not_awaited()
    embedder.assert_not_awaited()
    writer.apply_projection_batch.assert_not_awaited()


@pytest.mark.parametrize("recheck", ["rebuild", "reuse"])
async def test_parse_worker_takes_over_once_and_completes_projection(batch_environment, recheck):
    from bisheng.knowledge.domain.contracts.shared_space_storage import ProjectionContentInspection, SharedContentChunk
    from bisheng.knowledge.domain.services.document_projection_batch_service import DocumentProjectionBatchService

    factory, _ = batch_environment
    chunks = (SharedContentChunk(0, "恢复正文", [0.1, 0.2]),)
    source_writer = make_writer(apply_projection_batch=AsyncMock())
    source_writer.inspect_projection_content = AsyncMock(
        return_value={
            91: ProjectionContentInspection("rebuild", "both stores empty"),
        }
    )
    loader = AsyncMock(return_value=chunks)

    async def dispatch(tenant_id, entry_ids, reservation):
        async def write(plans, *, guard):
            await guard()
            async with factory() as repository:
                duplicate = await repository.claim_batch(entry_ids, "duplicate", 4, handoff_owner=reservation)
                assert not duplicate.claimed
            return {}

        writer = make_writer(apply_projection_batch=AsyncMock(side_effect=write))
        writer.inspect_projection_content = AsyncMock(
            return_value={
                91: ProjectionContentInspection(recheck, "fresh content check", chunks if recheck == "reuse" else ()),
            }
        )
        consumer = DocumentProjectionBatchService(
            repository_factory=factory,
            writer=writer,
            chunk_loader=loader,
            finalizer=AsyncMock(),
            allow_content_rebuild=True,
            handoff_owner=reservation,
        )
        assert await consumer.run(tenant_id, entry_ids, "parse-owner") == {101: "ready", 102: "ready"}
        assert await consumer.run(tenant_id, entry_ids, "redelivery") == {101: "not_claimed", 102: "not_claimed"}

    source = DocumentProjectionBatchService(
        repository_factory=factory,
        writer=source_writer,
        finalizer=AsyncMock(),
        rebuild_dispatch=dispatch,
    )
    assert await source.run(7, [101, 102], "source") == {101: "rebuild_queued", 102: "rebuild_queued"}
    assert loader.await_count == int(recheck == "rebuild")
    source_writer.apply_projection_batch.assert_not_awaited()
    async with factory() as repository:
        rows = await repository.find_by_ids([101, 102])
        assert all(row.projection_status == "ready" and row.projection_lease_owner is None for row in rows)


async def test_broker_failure_retains_bounded_retry_and_releases_reservation(batch_environment):
    from bisheng.knowledge.domain.contracts.shared_space_storage import ProjectionContentInspection
    from bisheng.knowledge.domain.services.document_projection_batch_service import DocumentProjectionBatchService

    factory, _ = batch_environment
    writer = make_writer(apply_projection_batch=AsyncMock())
    writer.inspect_projection_content = AsyncMock(return_value={91: ProjectionContentInspection("rebuild", "missing")})
    publish = AsyncMock(side_effect=ConnectionError("broker unavailable"))
    service = DocumentProjectionBatchService(
        repository_factory=factory,
        writer=writer,
        finalizer=AsyncMock(),
        rebuild_dispatch=publish,
        max_attempts=2,
    )
    assert await service.run(7, [101], "source") == {101: "exhausted"}
    assert publish.await_count == 2
    async with factory() as repository:
        row = await repository.find_by_id(101)
        assert row.projection_retry_count == 2 and row.projection_lease_owner is None
        assert "rebuild_publish_failed" in row.projection_last_error


async def test_abandoned_handoff_is_recoverable_without_resetting_failure_budget(batch_environment):
    from datetime import timedelta

    factory, _ = batch_environment
    async with factory() as repository:
        row = await repository.find_by_id(101)
        row.projection_retry_count = 1
        repository.session.add(row)
        await repository.session.commit()
        context = await repository.claim_batch([101], "source", 2)
        await repository.settle(context.claimed, "source", {}, 2, rebuild_ids={101}, rebuild_owner="rebuild:lost")
    async with factory() as repository:
        candidates = await repository.find_projection_candidates(now=datetime.now(), limit=100, max_retries=2)
        assert 101 not in {row.id for row in candidates}
        row = await repository.find_by_id(101)
        row.projection_lease_until = datetime.now() - timedelta(seconds=1)
        repository.session.add(row)
        await repository.session.commit()
    async with factory() as repository:
        context = await repository.claim_batch([101], "recovery", 2)
        assert context.claimed[0].projection_retry_count == 1
        await repository.settle(context.claimed, "recovery", {}, 2, rebuild_ids={101}, rebuild_owner="rebuild:new")
    async with factory() as repository:
        assert not (await repository.claim_batch([101], "old-delivery", 2, handoff_owner="rebuild:lost")).claimed
    async with factory() as repository:
        context = await repository.claim_batch([101], "parse-owner", 2, handoff_owner="rebuild:new")
        assert await repository.settle(context.claimed, "parse-owner", {101: "parse failed"}, 2) == {101: "exhausted"}


async def test_handoff_preserves_known_content_manifest_across_workers(batch_environment):
    from bisheng.knowledge.domain.contracts.shared_space_storage import ProjectionContentInspection, SharedContentChunk
    from bisheng.knowledge.domain.services.document_projection_batch_service import DocumentProjectionBatchService

    factory, _ = batch_environment
    chunks = (SharedContentChunk(0, "第一块", [0.1, 0.2]), SharedContentChunk(1, "第二块", [0.3, 0.4]))
    full = ProjectionContentInspection("reuse", "full content", chunks)
    partial = ProjectionContentInspection("reuse", "both stores have only first chunk", chunks[:1])
    writer = make_writer(apply_projection_batch=AsyncMock(return_value={91: "second chunk write failed"}))
    writer.inspect_projection_content = AsyncMock(side_effect=[{91: full}, {91: partial}])
    loader = AsyncMock(return_value=chunks)

    async def dispatch(tenant_id, entry_ids, reservation, *, content_manifests):
        consumer_writer = make_writer(apply_projection_batch=AsyncMock(return_value={}))
        consumer_writer.inspect_projection_content = AsyncMock(return_value={91: partial})
        consumer = DocumentProjectionBatchService(
            repository_factory=factory,
            writer=consumer_writer,
            chunk_loader=loader,
            finalizer=AsyncMock(),
            allow_content_rebuild=True,
            handoff_owner=reservation,
            content_manifests=content_manifests,
        )
        assert await consumer.run(tenant_id, entry_ids, "parse-owner") == {101: "ready"}
        assert len(consumer_writer.apply_projection_batch.await_args.args[0][0].content.chunks) == 2

    source = DocumentProjectionBatchService(
        repository_factory=factory,
        writer=writer,
        finalizer=AsyncMock(),
        rebuild_dispatch=dispatch,
        max_attempts=2,
    )
    assert await source.run(7, [101], "source") == {101: "rebuild_queued"}
    loader.assert_awaited_once()
