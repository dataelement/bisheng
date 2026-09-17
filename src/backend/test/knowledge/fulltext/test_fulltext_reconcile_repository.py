from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import text

from bisheng.knowledge.domain.contracts.fulltext_reconcile import Mutation, Observation, ReconcileReadError
from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_reconcile_repository_impl import (
    KnowledgeFulltextReconcileRepository,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_reconcile_source_repository_impl import (
    KnowledgeFulltextReconcileSourceRepository,
)


@pytest.fixture
async def source_session(async_db_session, monkeypatch):
    await async_db_session.execute(
        text("ALTER TABLE knowledge_space_scope ADD COLUMN portal_discovery_enabled INTEGER NOT NULL DEFAULT 0")
    )
    await async_db_session.execute(
        text(
            "INSERT INTO knowledge (id, tenant_id, name, index_name, auth_type) VALUES (198, 1, '制度库', 'rag', 'PUBLIC')"
        )
    )
    await async_db_session.execute(
        text("""
        INSERT INTO knowledgefile (id, tenant_id, user_id, knowledge_id, file_name, file_type,
          file_source, status, reference_document_id, projection_status, object_name)
        VALUES (10, 1, 1, 198, 'a.md', 1, 'upload', 2, NULL, 'pending', 'a.md'),
               (11, 1, 1, 198, 'b.md', 1, 'upload', 2, NULL, 'pending', 'b.md'),
               (12, 1, 1, 999, 'orphan.md', 1, 'upload', 2, NULL, 'pending', 'orphan.md'),
               (13, 1, 1, 198, 'logical.md', 1, 'upload', 2, 777, 'ready', 'logical.md')
    """)
    )
    config = AsyncMock(return_value=SimpleNamespace(portal=SimpleNamespace(document_types=[])))
    monkeypatch.setattr(
        "bisheng.shougang_portal_config.domain.services.portal_config_service.ShougangPortalConfigService.get_config",
        config,
    )
    await async_db_session.commit()
    return async_db_session, config


async def test_batch_snapshot_preserves_valid_files_and_rejects_incomplete_relations(source_session):
    session, config = source_session
    repo = KnowledgeFulltextReconcileSourceRepository(session)
    repo._execute = AsyncMock(wraps=repo._execute)
    snapshots = await repo.snapshots([10, 11, 12, 13, 14])
    assert snapshots[10].file_name == "a.md"
    assert snapshots[11].knowledge_name == "制度库"
    assert isinstance(snapshots[12], ReconcileReadError)
    assert isinstance(snapshots[13], ReconcileReadError)
    assert 14 not in snapshots
    assert repo._execute.await_count == 3
    config.assert_awaited_once()
    assert await repo.page_ids(10, 12, 1) == [11]
    assert await repo.upper_bound() == 13


async def test_claim_rechecks_mysql_and_does_not_reset_busy_outbox(source_session, monkeypatch):
    session, _ = source_session
    repo = KnowledgeFulltextReconcileRepository(session)
    before = await repo.source.snapshots([10, 11])
    mutations = [Mutation(i, {"file_id": i}, Observation(None)) for i in (10, 11)]
    now = datetime(2026, 9, 17, 1)
    track = MagicMock()
    monkeypatch.setattr(
        "bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_outbox_repository_impl.track_outbox_after_commit",
        track,
    )
    claimed, rejected = await repo.claim_mutations(mutations, before, "owner", now)
    assert set(claimed) == {10, 11}
    assert not rejected
    track.assert_not_called()
    row = (await repo.outboxes([10]))[10]
    revision = row.desired_revision
    claimed, rejected = await repo.claim_mutations(mutations, before, "other", now)
    assert not claimed
    assert rejected == {10: "busy_outbox", 11: "busy_outbox"}
    assert row.desired_revision == revision
    await repo.finish_mutations({10: (int(row.id), revision)}, {10}, "owner", now)
    await session.commit()
    await session.execute(text("UPDATE knowledgefile SET file_name='changed.md' WHERE id=10"))
    _, rejected = await repo.claim_mutations([mutations[0]], before, "other", now)
    assert rejected == {10: "source_changed"}


async def test_source_repair_reservation_blocks_legacy_auto_repair_and_duplicate_execution(source_session):
    from bisheng.knowledge.domain.models.knowledge_fulltext_reconcile import FulltextReconcileIssue

    session, _ = source_session
    connection = await session.connection()
    await connection.run_sync(FulltextReconcileIssue.__table__.create)
    repo = KnowledgeFulltextReconcileRepository(session)
    now = datetime(2026, 9, 17, 1)
    source = (await repo.source.snapshots([10]))[10]
    assert await repo.request_repair(source, now) == "repair_pending"
    ticket = await session.get(FulltextReconcileIssue, ("repair", 10))
    row = (await repo.outboxes([10]))[10]
    assert (
        await repo.outbox.request_auto_repair(
            outbox_id=row.id,
            revision=row.desired_revision,
            lease_owner=None,
            fingerprint=ticket.fingerprint,
            error_type="KnowledgeFulltextChunkCorruptedError",
            now=now,
        )
        == "exhausted"
    )
    assert await repo.begin_repair(10, ticket.fingerprint, ticket.task_id, now) == "parse"
    assert await repo.begin_repair(10, ticket.fingerprint, ticket.task_id, now) is None
    await repo.finish_repair(10, ticket.fingerprint, ticket.task_id, "parse", True, now)
    await session.refresh(ticket)
    assert ticket.status == "exhausted"
    assert ticket.attempts == 1


async def test_exhausted_outbox_with_verified_source_can_be_reconciled(source_session):
    session, _ = source_session
    repo = KnowledgeFulltextReconcileRepository(session)
    now = datetime(2026, 9, 17, 1)
    snapshots = await repo.source.snapshots([10])
    changes = [Mutation(10, {"file_id": 10}, Observation(None))]
    claimed, _ = await repo.claim_mutations(changes, snapshots, "first", now)
    row = (await repo.outboxes([10]))[10]
    row.retry_count = row.max_retries
    row.lease_until = now - timedelta(seconds=1)
    session.add(row)
    await session.flush()
    claimed, rejected = await repo.claim_mutations(changes, snapshots, "second", now)
    assert not rejected
    assert claimed[10][1] == 2
