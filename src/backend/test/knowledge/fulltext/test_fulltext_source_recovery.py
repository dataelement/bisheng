"""真实关联查询的三入口契约，以及关联恢复后的对账闭环。"""

from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from bisheng.knowledge.domain.contracts.fulltext_reconcile import ReconcileSourceRelationError
from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_reconcile_source_repository_impl import (
    KnowledgeFulltextReconcileSourceRepository,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_source_repository_impl import (
    KnowledgeFulltextSourceRepositoryImpl,
)
from bisheng.knowledge.domain.services.knowledge_fulltext_document_service import KnowledgeFulltextDocumentService
from test.knowledge.fulltext.test_fulltext_reconcile_repository import source_session as source_session


async def load(session, path, file_id):
    repository = KnowledgeFulltextSourceRepositoryImpl(session)
    if path == "single":
        return await repository.get_current_snapshot(file_id)
    if path == "batch":
        value = (await repository.get_current_snapshots([file_id]))[file_id]
    else:
        value = (await KnowledgeFulltextReconcileSourceRepository(session).snapshots([file_id]))[file_id]
    if isinstance(value, Exception):
        raise value
    return value


@pytest.mark.parametrize("path", ["single", "batch", "reconcile"])
async def test_physical_primary_file_keeps_identity_and_resolves_canonical_content(source_session, path, monkeypatch):
    session, _ = source_session
    await session.execute(text("UPDATE knowledge SET type=3 WHERE id=198"))
    await session.execute(
        text(
            "INSERT INTO knowledge_document (id,tenant_id,knowledge_id,primary_version_id,lifecycle_status,content_generation) VALUES (500,1,198,501,'active',7)"
        )
    )
    await session.execute(
        text(
            "INSERT INTO knowledge_document_version (id,document_id,knowledge_file_id,version_no,is_primary) VALUES (501,500,10,1,1)"
        )
    )
    result = await load(session, path, 10)
    assert result.logical_document_id is None
    assert result.canonical_document_id == 500
    assert result.document_version_id == 501
    assert result.content_generation == 7
    assert KnowledgeFulltextDocumentService.decide(result).value == "upsert"
    from bisheng.knowledge.domain.models.knowledge_space_shared_storage import KnowledgeSpaceSharedStorageRouting
    from bisheng.knowledge.domain.repositories.implementations import (
        knowledge_fulltext_source_repository_impl as module,
    )

    connection = await session.connection()
    await connection.run_sync(KnowledgeSpaceSharedStorageRouting.__table__.create, checkfirst=True)
    session.add(
        KnowledgeSpaceSharedStorageRouting(
            tenant_id=1,
            index_name="shared-es",
            collection_name="shared",
            embedding_model_id=7,
            schema_fingerprint="fp",
        )
    )
    await session.flush()
    monkeypatch.setattr(module, "get_shared_storage_conf", lambda: SimpleNamespace(es_routing_enabled=False))
    if path == "reconcile":
        source = (await KnowledgeFulltextReconcileSourceRepository(session).chunk_sources([result]))[10]
    elif path == "batch":
        source = (await KnowledgeFulltextSourceRepositoryImpl(session).get_chunk_sources([result]))[10]
    else:
        source = await KnowledgeFulltextSourceRepositoryImpl(session).get_chunk_source(result)
    assert source.canonical_document_id == 500
    assert source.canonical_version_id == 501
    assert source.index_name == "shared-es"
    assert "canonical_document_id" not in result.model_dump()


@pytest.mark.parametrize("path", ["single", "batch", "reconcile"])
async def test_deleted_entry_can_be_removed_even_when_reference_is_broken(source_session, path):
    session, _ = source_session
    await session.execute(text("UPDATE knowledgefile SET deleted_at=:now WHERE id=13"), {"now": datetime(2026, 9, 28)})
    result = await load(session, path, 13)
    assert KnowledgeFulltextDocumentService.decide(result).value == "delete"


@pytest.mark.parametrize("path", ["single", "batch", "reconcile"])
@pytest.mark.parametrize("case", ["missing_document", "missing_primary", "wrong_document", "missing_content"])
async def test_broken_relations_are_explicit_and_never_request_parse(source_session, path, case):
    from bisheng.knowledge.domain.services.knowledge_fulltext_auto_repair_service import (
        KnowledgeFulltextAutoRepairService,
    )

    session, _ = source_session
    expected = "document_missing"
    if case != "missing_document":
        await session.execute(
            text(
                "INSERT INTO knowledge_document (id,tenant_id,knowledge_id,primary_version_id,lifecycle_status) VALUES (777,1,198,501,'active')"
            )
        )
        expected = "primary_version_missing"
    if case in {"wrong_document", "missing_content"}:
        await session.execute(
            text(
                "INSERT INTO knowledge_document_version (id,document_id,knowledge_file_id,version_no,is_primary) VALUES (501,:doc,999,1,1)"
            ),
            {"doc": 778 if case == "wrong_document" else 777},
        )
        expected = "version_document_mismatch" if case == "wrong_document" else "content_file_missing"
    with pytest.raises(ReconcileSourceRelationError) as caught:
        await load(session, path, 13)
    assert caught.value.code == expected
    assert not caught.value.retryable
    assert KnowledgeFulltextAutoRepairService.decide(caught.value, retry_count=8).value == "ignore"


async def test_processing_relation_failure_is_retryable_and_state_change_changes_fingerprint(source_session):
    session, _ = source_session
    await session.execute(text("UPDATE knowledgefile SET status=1 WHERE id=13"))
    with pytest.raises(ReconcileSourceRelationError) as pending:
        await load(session, "reconcile", 13)
    assert pending.value.retryable
    await session.execute(text("UPDATE knowledgefile SET status=2 WHERE id=13"))
    with pytest.raises(ReconcileSourceRelationError) as failed:
        await load(session, "reconcile", 13)
    assert not failed.value.retryable
    assert pending.value.fingerprint != failed.value.fingerprint


async def test_orphan_knowledge_is_not_mistaken_for_missing_file(source_session):
    session, _ = source_session
    with pytest.raises(ReconcileSourceRelationError, match="knowledge_missing"):
        await load(session, "single", 12)


async def test_real_relations_recover_only_after_fulltext_is_verified(source_session):
    from bisheng.knowledge.domain.models.knowledge_fulltext_reconcile import (
        FulltextReconcileIssue,
        FulltextReconcileRun,
    )
    from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_reconcile_repository_impl import (
        KnowledgeFulltextReconcileRepository,
    )
    from bisheng.knowledge.domain.schemas.knowledge_fulltext_schema import KnowledgeFulltextChunk
    from test.knowledge.fulltext.test_fulltext_reconcile_service import Harness

    session, _ = source_session
    connection = await session.connection()
    for model in (FulltextReconcileRun, FulltextReconcileIssue):
        await connection.run_sync(model.__table__.create, checkfirst=True)
    repo = KnowledgeFulltextReconcileRepository(session)
    harness = Harness({})
    harness.repo = repo
    harness.documents[13] = {"file_id": 13, "content": "保留的旧正文"}
    now = datetime(2026, 9, 28)
    harness.service.now = lambda: now
    run = await repo.state.load_or_create(now, 13)
    failures, successes = await harness.service.batch([13], run.id)
    await repo.state.checkpoint(run.id, "forward", 13, failures, successes, now)
    assert failures == {13: "source_blocked:document_missing"}
    assert harness.documents[13]["content"] == "保留的旧正文"
    harness.es.chunks.assert_not_awaited()
    harness.es.write.assert_not_awaited()
    issue = await session.get(FulltextReconcileIssue, ("source", 13))

    # 恢复权威关系之后，ES 不可读时仍不能宣告问题解决。
    await session.execute(
        text(
            "INSERT INTO knowledge_document (id,tenant_id,knowledge_id,primary_version_id,lifecycle_status) VALUES (777,1,198,501,'active')"
        )
    )
    await session.execute(
        text(
            "INSERT INTO knowledge_document_version (id,document_id,knowledge_file_id,version_no,is_primary) VALUES (501,777,10,1,1)"
        )
    )
    await session.execute(text("UPDATE knowledgefile SET entry_type='publish',entry_status='active' WHERE id=13"))
    # 批量源查询始终读取路由表，普通知识库仍使用自己的 RAG 索引。
    from bisheng.knowledge.domain.models.knowledge_space_shared_storage import KnowledgeSpaceSharedStorageRouting

    await connection.run_sync(KnowledgeSpaceSharedStorageRouting.__table__.create, checkfirst=True)
    harness.es.read.side_effect = lambda ids: {i: OSError("ES unavailable") for i in ids}
    failures, successes = await harness.service.batch([13], run.id)
    await repo.state.checkpoint(run.id, "retry", 13, failures, successes, now)
    assert not successes
    assert issue.status == "blocked"

    harness.es.read.side_effect = harness.read
    harness.es.chunks.side_effect = lambda sources: {
        s.file_id: [
            KnowledgeFulltextChunk(
                es_id="chunk", document_id=s.file_id, knowledge_id=s.knowledge_id, chunk_index=0, text="恢复的正文"
            )
        ]
        for s in sources
    }
    harness.es.write.side_effect = lambda changes: {item.file_id: None for item in changes}
    failures, successes = await harness.service.batch([13], run.id)
    await repo.state.checkpoint(run.id, "retry", 13, failures, successes, now)
    assert failures == {13: "verify_failed"}
    assert issue.status == "blocked"
    # 普通消费预算耗尽后，对账可使用已校验正文接管，但仍须重新回读。
    outbox = (await repo.outboxes([13]))[13]
    outbox.retry_count = outbox.max_retries
    session.add(outbox)
    await session.flush()
    harness.es.write.side_effect = harness.write
    failures, successes = await harness.service.batch([13], run.id)
    assert not failures
    assert successes == {13: "repaired"}
    await repo.state.checkpoint(run.id, "retry", 13, failures, successes, now)
    await session.refresh(issue)
    assert issue.status == "resolved"
    assert harness.documents[13]["content"] == "恢复的正文"


async def test_queued_repair_is_settled_if_relation_breaks_before_execution(source_session):
    from bisheng.knowledge.domain.models.knowledge_fulltext_reconcile import FulltextReconcileIssue
    from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_reconcile_repository_impl import (
        KnowledgeFulltextReconcileRepository,
    )

    session, _ = source_session
    connection = await session.connection()
    await connection.run_sync(FulltextReconcileIssue.__table__.create, checkfirst=True)
    repo = KnowledgeFulltextReconcileRepository(session)
    now = datetime(2026, 9, 28)
    ticket = await repo.state.request_repair(13, "old-fingerprint", "projection", now)
    assert await repo.begin_repair(13, ticket.fingerprint, ticket.task_id, now) is None
    assert ticket.status == "exhausted"
    source_issue = await session.get(FulltextReconcileIssue, ("source", 13))
    assert source_issue.reason == "document_missing"
    assert await repo.state.pending_repairs(now) == []


async def test_ambiguous_source_fingerprint_is_order_independent(source_session, monkeypatch):
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
    from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_source_identity import (
        unique_source_row,
    )

    session, _ = source_session
    repository = KnowledgeFulltextSourceRepositoryImpl(session)
    row = (await repository._execute(repository._snapshot_statement().where(KnowledgeFile.id == 10))).one()
    # 当前唯一约束禁止重复版本，在查询边界模拟旧数据或异常联接产生的重复行。
    alternate = list(row)
    alternate[4] = SimpleNamespace(id=601, document_id=600, knowledge_file_id=10, is_primary=True)
    rows = [row, tuple(alternate)]
    fingerprints = []
    for order in (rows, list(reversed(rows))):
        with pytest.raises(ReconcileSourceRelationError) as caught:
            unique_source_row(order)
        fingerprints.append(caught.value.fingerprint)
    assert fingerprints[0] == fingerprints[1]
    execute = KnowledgeFulltextSourceRepositoryImpl._execute

    async def execute_with_ambiguous_rows(self, statement):
        if len(statement.column_descriptions) == 8:
            return SimpleNamespace(all=lambda: rows)
        return await execute(self, statement)

    monkeypatch.setattr(KnowledgeFulltextSourceRepositoryImpl, "_execute", execute_with_ambiguous_rows)
    for path in ("single", "batch", "reconcile"):
        with pytest.raises(ReconcileSourceRelationError, match="ambiguous_relations") as caught:
            await load(session, path, 10)
        assert caught.value.fingerprint == fingerprints[0]
