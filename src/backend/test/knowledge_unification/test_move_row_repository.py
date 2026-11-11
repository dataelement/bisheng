"""T945: actual owned-Root FK joins preserve malformed descendants for rejection."""

import pytest
from sqlalchemy import event
from sqlmodel import Session
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.tag import TagLink
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
from bisheng.knowledge.domain.repositories.move_row_repository import MoveRowRepository
from test.knowledge_unification import test_move_scope_repository as fixtures

store, tenant, moving = fixtures.store, fixtures.tenant, fixtures.moving


@pytest.mark.parametrize("kind", ["file", "tag", "job", "item", "item_parent"])
async def test_owned_root_does_not_hide_foreign_children_or_parent_job(moving, kind):
    job = KnowledgeProcessingJob(
        id="job",
        tenant_id=101,
        space_id=10,
        kind="move_index",
        actor_user_id=7,
        idempotency_key="job",
        request_hash="a" * 64,
        expected_model_config_revision=4,
    )
    item = KnowledgeProcessingItem(
        id="item",
        tenant_id=101,
        job_id="job",
        file_id=81,
        document_id=80,
        version_id=181,
        expected_space_id=11,
    )
    with Session(moving.sync) as session, bypass_tenant_filter():
        session.add_all([job, item])
        if kind == "file":
            session.add(KnowledgeFile(id=90, tenant_id=202, knowledge_id=10, file_name="foreign", file_type=0))
            model, key = KnowledgeFile, 90
        elif kind == "tag":
            session.get(TagLink, 1).tenant_id = 202
            model, key = TagLink, 1
        elif kind == "job":
            job.tenant_id = 202
            model, key = KnowledgeProcessingJob, "job"
        else:
            if kind == "item":
                item.tenant_id = 202
            else:
                job.tenant_id = 202
            model, key = KnowledgeProcessingItem, "item"
        session.commit()
    async with AsyncSession(moving.engine) as session:
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await MoveRowRepository()._by_ids(session, model, ("id",), [key])


@pytest.mark.parametrize("broken", ["missing_doc", "foreign_doc", "missing_file", "foreign_file", "dir"])
async def test_both_version_fk_entries_preserve_the_real_incomplete_chain(moving, broken):
    from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument

    with Session(moving.sync) as session, bypass_tenant_filter():
        file_id, doc_id = 81, 80
        if broken == "missing_doc":
            doc_id = 999
        elif broken == "foreign_doc":
            session.add(KnowledgeDocument(id=90, knowledge_id=20))
            doc_id = 90
        elif broken == "missing_file":
            file_id = 999
        elif broken == "foreign_file":
            session.add(KnowledgeFile(id=90, tenant_id=202, knowledge_id=20, file_name="foreign"))
            file_id = 90
        else:
            file_id, doc_id = 50, 999
        session.add(KnowledgeDocumentVersion(id=190, document_id=doc_id, knowledge_file_id=file_id, version_no=3))
        session.commit()
    key = "document_id" if broken in ("missing_file", "foreign_file") else "knowledge_file_id"
    wanted = doc_id if key == "document_id" else file_id
    async with AsyncSession(moving.engine) as session:
        rows = await MoveRowRepository()._by_ids(
            session,
            KnowledgeDocumentVersion,
            ("id", "document_id", "knowledge_file_id"),
            [wanted],
            key=key,
        )
        assert 190 in {row["id"] for row in rows}
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await fixtures.load(moving, session)


async def test_reader_never_flushes_caller_pending_or_returns_anchor_columns(moving):
    reads, writes = [], []

    def record(conn, cursor, sql, params, context, many):
        (reads if sql.lstrip().upper().startswith("SELECT") else writes).append(sql)

    event.listen(moving.engine.sync_engine, "before_cursor_execute", record)
    try:
        async with AsyncSession(moving.engine) as session:
            pending = KnowledgeFile(tenant_id=101, knowledge_id=10, file_name="caller-pending")
            session.add(pending)
            rows = await MoveRowRepository()._by_ids(session, KnowledgeFile, ("id", "knowledge_id"), [81], lock=True)
            assert rows == [{"id": 81, "knowledge_id": 10}]
            assert pending in session.new and pending.id is None
    finally:
        event.remove(moving.engine.sync_engine, "before_cursor_execute", record)
    assert not writes and len(reads) == 2
    assert "JOIN knowledgefile ON" in reads[0]
    assert "JOIN" not in reads[1]
