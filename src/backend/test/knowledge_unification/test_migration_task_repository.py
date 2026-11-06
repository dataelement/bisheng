"""T807: real native SQL task facts are bounded and never task authority."""

import importlib
from dataclasses import FrozenInstanceError
from datetime import datetime

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem as Item
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob as Job
from bisheng.knowledge.domain.models.knowledge_space_delete_job import KnowledgeSpaceDeleteJob as DeleteJob
from test.knowledge_unification import test_migration_resource_repository as resources

resource_native = resources.native
NOW = datetime(2026, 11, 7, 1, 2, 3)


@pytest.fixture
async def native(resource_native):
    async with resource_native.engine.begin() as connection:
        for model in (Job, Item, DeleteJob):
            await connection.run_sync(lambda conn, model=model: model.__table__.create(conn))
    return resource_native


@pytest.fixture
def repo():
    return importlib.import_module(
        "bisheng.knowledge.domain.repositories.unification_task_repository"
    ).UnificationTaskRepository()


def job(ident="job-0000", tenant=101, **changes):
    return dict(
        id=ident,
        tenant_id=tenant,
        space_id=9000,
        kind="embedding_rebuild",
        state="accepted",
        actor_user_id=7,
        actor_reference={"credential": "private-credential"},
        idempotency_key=ident,
        request_hash="a" * 64,
        parameters={"callback_url": "https://private-callback/?secret=private-value"},
        scope_manifest=[{"private-scope": "original"}],
        expected_model_config_revision=0,
        create_time=NOW,
        update_time=NOW,
        **changes,
    )


def item(ident="item-0000", **changes):
    values = {
        "id": ident,
        "tenant_id": 101,
        "job_id": "job-0000",
        "file_id": 1,
        "document_id": 10,
        "version_id": 20,
        "expected_space_id": 9000,
        "processing_snapshot": {"secret": "private-snapshot"},
        "state": "pending",
        "checkpoint": {"private-checkpoint": "keep"},
        "result": {"private-result": "keep"},
        "create_time": NOW,
        "update_time": NOW,
    }
    return values | changes


def deletion(ident="delete-0000", **changes):
    return {
        "id": ident,
        "tenant_id": 101,
        "space_id": 9000,
        "applicant_user_id": 7,
        "manifest": {"objects": ["private-object"], "callback": "https://private-callback/"},
        "completed_steps": [],
        "state": "PENDING",
        "create_time": NOW,
        "update_time": NOW,
    } | changes


async def all_pages(repo, session, kind):
    rows, after = [], None
    while True:
        page = await getattr(repo, f"alist_{kind}")(session, after_id=after)
        rows.extend(page.items)
        if page.next_after is None:
            return rows
        after = page.next_after


async def test_global_all_state_job_seek_is_401_rows_in_three_selects_without_payload_export(repo, native):
    states = ("accepted", "running", "succeeded", "partial_failed", "failed", "obsolete")
    rows = [job(f"job-{i:04}", 101 if i % 2 == 0 else 202) | {"state": states[i % 6]} for i in range(401)]
    await native.insert(Job, rows)
    native.queries.clear()
    async with AsyncSession(native.engine) as session, session.begin():
        actual = await all_pages(repo, session, "jobs")
    assert [row.task_id for row in actual] == [row["id"] for row in rows]
    assert {row.tenant_id for row in actual} == {101, 202}
    assert {row.state for row in actual} == set(states)
    assert len(native.queries) == 3
    assert all(len(row.configuration_digest) == len(row.record_digest) == 64 for row in actual)
    assert "private-" not in repr(actual) and not hasattr(actual[0], "__dict__")
    with pytest.raises(FrozenInstanceError):
        actual[0].state = "succeeded"


async def test_item_seek_does_not_select_or_repeat_the_parent_scope_json(repo, native):
    await native.insert(Job, [job() | {"scope_manifest": [{"body": "private-scope" * 20000}]}])
    await native.insert(Item, [item(f"item-{i:04}", file_id=i + 1, version_id=i + 1) for i in range(401)])
    native.queries.clear()
    async with AsyncSession(native.engine) as session, session.begin():
        actual = await all_pages(repo, session, "items")
    assert len(actual) == 401 and len(native.queries) == 3
    assert all("scope_manifest" not in sql and "actor_reference" not in sql for sql, _ in native.queries)
    assert all(row.task_kind == "item" for row in actual)


@pytest.mark.parametrize(
    "kind,model,factory,column,value",
    [
        ("jobs", Job, job, "parameters", {"private": "changed"}),
        ("items", Item, item, "processing_snapshot", {"private": "changed"}),
        ("delete_jobs", DeleteJob, deletion, "manifest", {"private": "changed"}),
    ],
)
async def test_digests_bind_actual_configuration_without_exporting_it(
    repo, native, kind, model, factory, column, value
):
    if model is Item:
        await native.insert(Job, [job()])
    await native.insert(model, [factory()])
    async with AsyncSession(native.engine) as session, session.begin():
        first = (await getattr(repo, f"alist_{kind}")(session)).items[0]
    async with native.engine.begin() as connection:
        await connection.execute(sa.update(model.__table__).values({column: value}))
    async with AsyncSession(native.engine) as session, session.begin():
        second = (await getattr(repo, f"alist_{kind}")(session)).items[0]
    assert first.configuration_digest != second.configuration_digest
    assert first.record_digest != second.record_digest
    assert "private" not in repr(second)


async def test_delete_completed_history_and_failed_steps_are_not_filtered(repo, native):
    await native.insert(
        DeleteJob, [deletion(f"delete-{i}", state=state) for i, state in enumerate(("PENDING", "RUNNING", "SUCCEEDED"))]
    )
    async with AsyncSession(native.engine) as session, session.begin():
        rows = await all_pages(repo, session, "delete_jobs")
    assert [row.state for row in rows] == ["PENDING", "RUNNING", "SUCCEEDED"]


async def test_exact_file_lookup_keeps_missing_unregistered_and_other_tenant_facts(repo, native):
    await native.insert(resources.Knowledge, [resources.resource(9000), resources.resource(8000, tenant=202)])
    await native.insert(resources.KnowledgeFile, [resources.file(1), resources.file(2, tenant=202, knowledge_id=8000)])
    async with AsyncSession(native.engine) as session, session.begin():
        rows = await repo.aget_file_facts(session, file_ids=(2, 1, 3))
    assert [(row.file_id, row.exists, row.tenant_id, row.space_id) for row in rows] == [
        (2, True, 202, 8000),
        (1, True, 101, 9000),
        (3, False, None, None),
    ]
    assert rows[1].document_id is rows[1].version_id is None
    assert "private" not in repr(rows)


async def test_file_lookup_batch_has_constant_select_budget_and_does_not_expand_duplicate_versions(repo, native):
    await native.insert(resources.Knowledge, [resources.resource(9000)])
    await native.insert(resources.KnowledgeFile, [resources.file(1)])
    await native.insert(resources.KnowledgeDocument, [{"id": 10, "knowledge_id": 9000}])
    await native.insert(
        resources.KnowledgeDocumentVersion,
        [
            {"id": i + 1, "document_id": 10, "knowledge_file_id": 1, "version_no": i + 1, "is_primary": False}
            for i in range(10001)
        ],
    )
    native.queries.clear()
    async with AsyncSession(native.engine) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.aget_file_facts(session, file_ids=(1,))
    assert len(native.queries) <= 2
    assert any("count(" in sql.lower() and "group by" in sql.lower() for sql, _ in native.queries)


@pytest.mark.parametrize("problem", ["foreign_space", "missing_document", "foreign_document"])
async def test_real_file_and_registered_chain_conflicts_are_not_downgraded_to_missing(repo, native, problem):
    await native.insert(resources.Knowledge, [resources.resource(9000), resources.resource(8000, tenant=202)])
    await native.insert(
        resources.KnowledgeFile, [resources.file(1, knowledge_id=8000 if problem == "foreign_space" else 9000)]
    )
    if problem != "foreign_space":
        if problem != "missing_document":
            await native.insert(resources.KnowledgeDocument, [{"id": 10, "knowledge_id": 8000}])
        await native.insert(
            resources.KnowledgeDocumentVersion,
            [{"id": 20, "document_id": 10, "knowledge_file_id": 1, "version_no": 1, "is_primary": True}],
        )
    async with AsyncSession(native.engine) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.aget_file_facts(session, file_ids=(1,))


@pytest.mark.parametrize("parent", [None, 202])
async def test_item_missing_or_foreign_parent_is_not_silently_hidden(repo, native, parent):
    if parent:
        await native.insert(Job, [job(tenant=parent)])
    await native.insert(Item, [item()])
    async with AsyncSession(native.engine) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.alist_items(session)


@pytest.mark.parametrize("changes", [{"limit": True}, {"limit": 201}, {"after_id": ""}, {"after_id": 1}])
async def test_invalid_seek_is_refused(repo, native, changes):
    async with AsyncSession(native.engine) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.alist_jobs(session, **changes)


async def test_readonly_original_transaction_does_not_flush_caller_pending_work(repo, native):
    await native.insert(resources.Knowledge, [resources.resource(9000)])
    async with AsyncSession(native.engine) as session:
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.alist_jobs(session)
        async with session.begin():
            root = await session.get(resources.Knowledge, 9000)
            root.name = "pending-caller-name"
            session.add(resources.KnowledgeFile(**resources.file(1)))
            flushes = []
            sa.event.listen(session.sync_session, "before_flush", lambda *args: flushes.append(True))
            assert not (await repo.alist_jobs(session)).items
            assert not (await repo.aget_file_facts(session, file_ids=(1,)))[0].exists
            assert not flushes and root in session.dirty
            with bypass_tenant_filter(), pytest.raises(KnowledgeOperationPlanConflictError):
                await repo.alist_jobs(session)
            await session.rollback()


async def test_registered_primary_and_history_are_exact_bounded_native_facts(repo, native):
    await native.insert(resources.Knowledge, [resources.resource(9000)])
    await native.insert(resources.KnowledgeFile, [resources.file(1), resources.file(2)])
    await native.insert(resources.KnowledgeDocument, [{"id": 10, "knowledge_id": 9000, "primary_version_id": 20}])
    await native.insert(
        resources.KnowledgeDocumentVersion,
        [
            {"id": 20, "document_id": 10, "knowledge_file_id": 1, "version_no": 1, "is_primary": True},
            {"id": 21, "document_id": 10, "knowledge_file_id": 2, "version_no": 2, "is_primary": False},
        ],
    )
    native.queries.clear()
    async with AsyncSession(native.engine) as session, session.begin():
        facts = await repo.aget_file_facts(session, file_ids=(2, 1))
    assert [(row.file_id, row.document_id, row.version_id) for row in facts] == [(2, 10, 21), (1, 10, 20)]
    assert len(native.queries) == 3


@pytest.mark.parametrize("kind", ["space", "job", "delete_job", "qa"])
async def test_broker_target_facts_are_exact_global_lightweight_and_do_not_export_originals(repo, native, kind):
    await native.insert(resources.Knowledge, [resources.resource(9000, tenant=202)])
    if kind == "job":
        await native.insert(
            Job,
            [
                job(tenant=202)
                | {
                    "scope_manifest": [{"private-body": "private" * 20000}],
                    "parameters": {"private-callback": "secret"},
                }
            ],
        )
    elif kind == "delete_job":
        await native.insert(DeleteJob, [deletion() | {"tenant_id": 202}])
    elif kind == "qa":
        await native.insert(
            resources.QAKnowledge,
            [
                {
                    "id": 12,
                    "tenant_id": 202,
                    "knowledge_id": 9000,
                    "user_id": 7,
                    "questions": ["private-question"],
                    "answers": "private-answer",
                }
            ],
        )
    method, parameter, ids = {
        "space": ("aget_space_facts", "space_ids", (9000, 9999)),
        "job": ("aget_job_facts", "job_ids", ("job-0000", "missing")),
        "delete_job": ("aget_delete_job_facts", "job_ids", ("delete-0000", "missing")),
        "qa": ("aget_qa_facts", "qa_ids", (12, 9999)),
    }[kind]
    native.queries.clear()
    async with AsyncSession(native.engine) as session, session.begin():
        actual = await getattr(repo, method)(session, **{parameter: ids})
    assert [(fact.target_id, fact.exists) for fact in actual] == [(ids[0], True), (ids[1], False)]
    assert actual[0].tenant_id == 202 and actual[0].space_id == 9000
    assert len(native.queries) == 1
    assert not any(
        name in native.queries[0][0]
        for name in ("scope_manifest", "actor_reference", "parameters", "manifest", "questions", "answers")
    )
    assert "private-" not in repr(actual) and not hasattr(actual[0], "__dict__")


async def test_broker_space_actual_operation_and_rg_are_preserved_without_model_binding(repo, native):
    await native.insert(
        resources.Knowledge,
        [
            resources.resource(9000)
            | {
                "model_config_revision": 4,
                "index_generation": "g4",
                "model_transition": {"operation_id": "accepted-op", "private-slot": "original"},
            }
        ],
    )
    async with AsyncSession(native.engine) as session, session.begin():
        fact = (await repo.aget_space_facts(session, space_ids=(9000,)))[0]
    assert (fact.operation_id, fact.revision, fact.index_generation) == ("accepted-op", 4, "g4")
    assert not hasattr(fact, "model_id") and "private" not in repr(fact)


async def test_broker_qa_foreign_parent_is_a_conflict_not_missing(repo, native):
    await native.insert(resources.Knowledge, [resources.resource(9000, tenant=202)])
    await native.insert(
        resources.QAKnowledge, [{"id": 12, "tenant_id": 101, "knowledge_id": 9000, "questions": [], "answers": ""}]
    )
    async with AsyncSession(native.engine) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.aget_qa_facts(session, qa_ids=(12,))


async def test_broker_exact_target_batches_are_bounded_empty_is_zero_sql(repo, native):
    async with AsyncSession(native.engine) as session, session.begin():
        for method, parameter in (
            ("aget_space_facts", "space_ids"),
            ("aget_job_facts", "job_ids"),
            ("aget_delete_job_facts", "job_ids"),
            ("aget_qa_facts", "qa_ids"),
        ):
            native.queries.clear()
            assert await getattr(repo, method)(session, **{parameter: ()}) == ()
            assert not native.queries
            with pytest.raises(KnowledgeOperationPlanConflictError):
                await getattr(repo, method)(session, **{parameter: tuple(range(1, 202))})
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.aget_space_facts(session, space_ids=(True,))
