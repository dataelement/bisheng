"""Default ordinary paging excludes move/copy before COUNT and LIMIT."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import sqlalchemy as sa

from bisheng.knowledge.application.processing_owner import KnowledgeProcessingOwner
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob as Job
from bisheng.knowledge.domain.repositories.processing_job_repository import ProcessingJobRepository
from bisheng.knowledge.domain.services import processing_job_service as module
from test.knowledge_unification.test_job_repo import job_session as job_session
from test.knowledge_unification.test_job_repo import job_tenant as job_tenant

ORDINARY = ("embedding_rebuild", "file_reprocess", "file_resplit", "metadata_schema_change")


async def seed(session, kinds, offset=0):
    result = []
    for number, kind in enumerate(kinds, offset + 1):
        job = Job(
            id=str(UUID(int=number)),
            tenant_id=101,
            space_id=1,
            kind=kind,
            actor_user_id=11,
            actor_reference={"original": True},
            idempotency_key=f"mixed-{number}",
            request_hash="0" * 64,
            expected_model_config_revision=7,
            expected_index_generation="index-7",
            accepted_at=datetime(2026, 11, 9) + timedelta(seconds=number),
        )
        session.add(job)
        result.append(job.id)
    await session.commit()
    return result


async def test_same_ordinary_results_and_query_count_with_explicit_predicate_in_count_and_page(job_session):
    repo = ProcessingJobRepository()
    await seed(job_session, ORDINARY * 2)
    captured = []

    def capture(connection, cursor, statement, params, context, many):
        captured.append((statement, params))

    engine = job_session.bind.sync_engine
    sa.event.listen(engine, "before_cursor_execute", capture)
    try:
        original = await repo.alist_jobs(job_session, 1, page=2, page_size=3)
        before = tuple(captured)
        captured.clear()
        filtered = await repo.alist_jobs(job_session, 1, page=2, page_size=3, ordinary_only=True)
        after = tuple(captured)
    finally:
        sa.event.remove(engine, "before_cursor_execute", capture)
    assert [row.id for row in filtered.rows] == [row.id for row in original.rows]
    assert filtered.total == original.total == 8 and len(before) == len(after) == 3
    assert before[0] == after[0]  # Existing space read is byte/bind identical.
    for statement, params in after[1:]:
        assert "knowledge_processing_job.kind IN (?, ?, ?, ?)" in statement
        assert all(kind in params for kind in ORDINARY)
    print(
        {
            "ordinary_original_sql": len(before),
            "ordinary_filtered_sql": len(after),
            "predicate_added_to": ["COUNT", "page"],
        }
    )


async def test_mixed_default_service_full_pages_and_total_are_only_four_supported_kinds(job_session, monkeypatch):
    expected = await seed(job_session, ORDINARY * 2)
    await seed(job_session, ("move_index", "space_copy", "move_index"), offset=20)

    async def permitted(*args, **kwargs):
        return None

    async def visible(*args, **kwargs):
        return {}

    monkeypatch.setattr(module, "require_business_action", permitted)
    monkeypatch.setattr(module, "batch_check_business_actions", visible)
    service = module.ProcessingJobService(owner=KnowledgeProcessingOwner(), available_kinds=ORDINARY)
    rows = []
    for page in range(1, 5):
        result = await service.alist(job_session, 1, identity=SimpleNamespace(user_id=11), page=page, page_size=3)
        assert result.total == 8
        rows.extend(result.data)
    assert [row.id for row in rows] == list(reversed(expected))
    assert {row.kind for row in rows} == set(ORDINARY)
    # The Repo default public port still returns every kind; only Service opted in.
    native = await service.jobs.alist_jobs(job_session, 1, page=1, page_size=20)
    assert native.total == 11 and len(native.rows) == 11
    explicit = await service.alist(job_session, 1, identity=None, page=1, page_size=20, kind="file_resplit")
    assert explicit.total == 2 and all(row.kind == "file_resplit" for row in explicit.data)
