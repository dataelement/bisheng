"""T737: actual Celery entry, native Owner/J1 and native index IO boundaries.

Only credential/FGA/broker and Milvus/ES transports are isolated. The real
Metadata Owner, model SourceRead runtime, handler, leases and SQL completion
remain in the call chain; no fake service accepts an unavailable kind.
"""

import sys
from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import event
from sqlmodel import Session, select

from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.core.ai import FakeEmbeddings
from bisheng.knowledge.application import model_reference_read, processing_identity
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
from bisheng.knowledge.domain.schemas.processing_job import ProcessingRetryRequest
from bisheng.knowledge.rag.elasticsearch_factory import ElasticsearchFactory
from bisheng.knowledge.rag.milvus_factory import MilvusFactory
from bisheng.worker import tenant_context as workers
from bisheng.worker.knowledge import processing_jobs as worker
from test.knowledge_unification import test_metadata_index_worker as native
from test.knowledge_unification import test_metadata_job as fixtures

store, tenant, business, admission = fixtures.store, fixtures.tenant, fixtures.business, fixtures.admission
processing, application, metadata, owner, flow = (
    fixtures.processing,
    fixtures.application,
    fixtures.metadata,
    fixtures.owner,
    fixtures.flow,
)


@pytest.fixture
async def execution(flow, monkeypatch):
    state = SimpleNamespace(
        flow=flow, open_sessions=0, events=[], es_fail_files=set(), sql=[], after_io=None, deny=False
    )
    rows = [native.record(number, file_id) for file_id in (81, 82) for number in (file_id * 10, file_id * 10 + 1)]

    class Collection(native.NativeCollection):
        def query_iterator(self, *, batch_size, limit, expr, output_fields):
            assert state.open_sessions == 0
            assert batch_size == 1000 and limit == -1
            assert output_fields == [field.name for field in self.schema.fields]
            file_id = int(expr.removeprefix("document_id == "))
            assert file_id in {81, 82} and expr == f"document_id == {file_id}"
            state.events.append(("milvus", file_id))
            iterator = native.NativeIterator(
                [row for row in self.records.values() if row["document_id"] == file_id], []
            )
            self.iterators.append(iterator)
            return iterator

        def upsert(self, data):
            assert state.open_sessions == 0
            result = super().upsert(data)
            if state.after_io is not None:
                state.after_io("milvus", data[0]["document_id"])
            return result

    state.collection = Collection(rows, [])
    state.es_rows = deepcopy(rows)

    @asynccontextmanager
    async def sessions():
        async with flow.context.sessions() as session:
            state.open_sessions += 1
            try:
                yield session
            finally:
                state.open_sessions -= 1

    def milvus(collection_name, embedding_function, **kwargs):
        assert state.open_sessions == 0 and collection_name == "col40"
        assert isinstance(embedding_function, FakeEmbeddings)
        return SimpleNamespace(col=state.collection)

    async def update(*, index, body, refresh):
        assert state.open_sessions == 0 and index == "idx40" and refresh is True
        file_id = body["query"]["term"]["metadata.document_id"]
        state.events.append(("es", file_id))
        if file_id in state.es_fail_files:
            raise RuntimeError("offline ES failure")
        params = body["script"]["params"]
        matched = [row for row in state.es_rows if row["document_id"] == file_id]
        for row in matched:
            values = deepcopy(row["user_metadata"])
            for field in params["affected_fields"]:
                values.pop(field, None)
            values.update(deepcopy(params["replacements"]))
            row["user_metadata"] = values
        if state.after_io is not None:
            state.after_io("es", file_id)
        return native.response(
            {
                "total": len(matched),
                "updated": len(matched),
                "deleted": 0,
                "noops": 0,
                "version_conflicts": 0,
                "timed_out": False,
                "failures": [],
            }
        )

    def elasticsearch(index_name, **kwargs):
        assert state.open_sessions == 0 and index_name == "idx40"
        return SimpleNamespace(client=SimpleNamespace(update_by_query=update, close=state.close))

    state.close = AsyncMock()

    async def resolve(*args, **kwargs):
        if state.deny:
            raise PermissionDeniedError()
        return flow.context.user

    state.resolve = AsyncMock(side_effect=resolve)
    state.publish = Mock()
    monkeypatch.setattr(worker, "get_async_db_session", sessions)
    monkeypatch.setattr(worker, "_new_owner", lambda: flow.owner)
    monkeypatch.setattr(worker, "_active_tenant_ids", AsyncMock(return_value=[101]))
    monkeypatch.setattr(worker, "require_business_action", AsyncMock())
    monkeypatch.setattr(processing_identity, "resolve_web_runtime_identity", state.resolve)
    monkeypatch.setattr("bisheng.permission.application.relation_api.is_tenant_admin", AsyncMock(return_value=False))
    monkeypatch.setattr(model_reference_read, "get_async_db_session", sessions)
    monkeypatch.setattr(model_reference_read, "_runtime", flow.runtime)
    monkeypatch.setattr(MilvusFactory, "init_vectorstore", milvus)
    monkeypatch.setattr(ElasticsearchFactory, "init_vectorstore", elasticsearch)
    monkeypatch.setattr(FakeEmbeddings, "embed_documents", Mock(side_effect=AssertionError("no embedding IO")))
    monkeypatch.setattr(FakeEmbeddings, "embed_query", Mock(side_effect=AssertionError("no embedding IO")))
    monkeypatch.setattr(worker.execute_processing_job, "apply_async", state.publish)
    # The dedicated runner is absent at the red baseline. Once production
    # assembly imports it, replace only its native Session factory, if owned.
    runner = sys.modules.get("bisheng.worker.knowledge.metadata_jobs")
    if runner is not None:
        monkeypatch.setattr(runner, "get_async_db_session", sessions, raising=False)
    async with flow.context.sessions() as session:
        root = await session.get(Knowledge, 40)
        root.index_name, root.collection_name = "idx40", "col40"
        await session.commit()
    sender = SimpleNamespace(
        name=worker.EXECUTE_TASK,
        request=SimpleNamespace(id="metadata-task", headers={"tenant_id": 101}, called_directly=False),
    )
    monkeypatch.setattr(workers, "current_task", SimpleNamespace(_get_current_object=lambda: sender))
    workers.restore_tenant_context(sender=sender)

    def query(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            state.sql.append(statement.lower().split(" from ", 1)[0])

    event.listen(flow.context.engine.sync_engine, "before_cursor_execute", query)
    try:
        yield state
    finally:
        event.remove(flow.context.engine.sync_engine, "before_cursor_execute", query)
        workers.reset_tenant_context(sender=sender)


async def run(execution, job_id):
    async with execution.flow.context.sessions() as session:
        revision = (await session.get(KnowledgeProcessingJob, job_id)).revision
    execution.sql.clear()
    return await worker._execute_processing_job(job_id, revision)


async def test_real_metadata_worker_visits_all_history_without_embedding_or_rebuild_state(execution):
    job_id, _ = await fixtures.seed_accepted(execution.flow)
    original = deepcopy(execution.collection.records)
    assert (await run(execution, job_id))["state"] == "succeeded"
    async with execution.flow.context.sessions() as session:
        job = await session.get(KnowledgeProcessingJob, job_id)
        root = await session.get(Knowledge, 40)
        items = (await session.exec(select(KnowledgeProcessingItem).order_by(KnowledgeProcessingItem.file_id))).all()
        assert (job.succeeded_count, job.failed_count, job.pending_count) == (2, 0, 0)
        assert [(item.file_id, item.state, item.attempt) for item in items] == [
            (81, "succeeded", 1),
            (82, "succeeded", 1),
        ]
        assert (root.model_config_revision, root.index_generation, root.metadata_schema_revision, root.state) == (
            0,
            "g0",
            1,
            1,
        )
        assert root.model == "11" and root.model_transition is None
        assert (await session.get(KnowledgeFile, 81)).user_metadata["alias"]["field_value"] == "private-value"
        assert (await session.get(KnowledgeFile, 81)).status == 2
        assert (await session.get(KnowledgeFile, 82)).status == 7
    assert execution.events == [("milvus", 81), ("es", 81), ("milvus", 82), ("es", 82)]
    assert all(iterator.closed for iterator in execution.collection.iterators)
    assert execution.close.await_count == 2 and execution.resolve.await_count >= 4
    assert not any("scope_manifest" in statement for statement in execution.sql)
    for pk, row in execution.collection.records.items():
        assert all(row[key] == original[pk][key] for key in ("pk", "vector", "text", "extra"))
        assert row["user_metadata"]["kept"] == original[pk]["user_metadata"]["kept"]
        assert "note" not in row["user_metadata"]
        assert row["user_metadata"].get("alias") == ("private-value" if row["document_id"] == 81 else None)


async def test_partial_native_es_failure_retries_only_failed_history_and_preserves_success(execution):
    job_id, _ = await fixtures.seed_accepted(execution.flow)
    execution.es_fail_files.add(82)
    assert (await run(execution, job_id))["state"] == "partial_failed"
    async with execution.flow.context.sessions() as session:
        job = await session.get(KnowledgeProcessingJob, job_id)
        successful = (
            await session.exec(select(KnowledgeProcessingItem).where(KnowledgeProcessingItem.file_id == 81))
        ).one()
        before = deepcopy(successful.model_dump())
        revision = job.revision
        assert (job.succeeded_count, job.failed_count) == (1, 1)
    execution.es_fail_files.clear()
    execution.events.clear()
    async with execution.flow.context.sessions() as session:
        outcome = await execution.flow.service.aretry(
            session,
            40,
            job_id,
            ProcessingRetryRequest(idempotency_key="native-metadata-retry", expected_job_revision=revision),
            identity=execution.flow.context.user,
            entry_kind="web",
        )
        assert outcome.error is None and outcome.data.state == "accepted"
        await session.commit()
    assert (await run(execution, job_id))["state"] == "succeeded"
    assert execution.events == [("milvus", 82), ("es", 82)]
    async with execution.flow.context.sessions() as session:
        successful = (
            await session.exec(select(KnowledgeProcessingItem).where(KnowledgeProcessingItem.file_id == 81))
        ).one()
        assert successful.model_dump() == before
        failed = (
            await session.exec(select(KnowledgeProcessingItem).where(KnowledgeProcessingItem.file_id == 82))
        ).one()
        assert failed.attempt == 2 and failed.state == "succeeded"
        root = await session.get(Knowledge, 40)
        assert (root.metadata_schema_revision, root.model_config_revision, root.index_generation, root.state) == (
            1,
            0,
            "g0",
            1,
        )


async def test_completed_empty_metadata_structure_never_dispatches_or_opens_index(execution):
    job_id, _ = await fixtures.seed_accepted(execution.flow, empty=True)
    assert await worker._dispatch_pending_processing_jobs() == 0
    assert (await run(execution, job_id))["state"] == "succeeded"
    execution.publish.assert_not_called()
    assert not execution.events
    async with execution.flow.context.sessions() as session:
        job = await session.get(KnowledgeProcessingJob, job_id)
        assert job.total_count == 0 and not job.pending_dispatch
        assert not (await session.exec(select(KnowledgeProcessingItem))).all()


@pytest.mark.parametrize("changed", ["schema", "model", "generation"])
async def test_guard_commits_obsolete_before_next_index_io_when_actual_configuration_changes(execution, changed):
    job_id, _ = await fixtures.seed_accepted(execution.flow)

    def change(stage, file_id):
        assert execution.open_sessions == 0
        if stage == "milvus":
            with Session(execution.flow.context.sync) as session:
                root = session.get(Knowledge, 40)
                if changed == "schema":
                    root.metadata_schema_revision += 2
                elif changed == "model":
                    root.model_config_revision += 1
                else:
                    root.index_generation = "changed-generation"
                session.commit()
            execution.after_io = None

    execution.after_io = change
    assert (await run(execution, job_id))["state"] == "obsolete"
    assert execution.events == [("milvus", 81)]
    async with execution.flow.context.sessions() as session:
        assert (await session.get(KnowledgeFile, 81)).user_metadata["note"]["field_value"] == "private-value"
        job = await session.get(KnowledgeProcessingJob, job_id)
        assert job.succeeded_count == 0 and not job.pending_dispatch


async def test_last_actor_restoration_rejects_after_io_before_file_and_item_completion(execution):
    job_id, _ = await fixtures.seed_accepted(execution.flow)
    execution.after_io = lambda stage, file_id: setattr(execution, "deny", stage == "es")
    assert (await run(execution, job_id))["state"] == "failed"
    assert execution.events == [("milvus", 81), ("es", 81)]
    async with execution.flow.context.sessions() as session:
        job = await session.get(KnowledgeProcessingJob, job_id)
        assert (job.succeeded_count, job.failed_count, job.pending_count) == (0, 2, 0)
        assert (await session.get(KnowledgeFile, 81)).user_metadata["note"]["field_value"] == "private-value"
        assert (await session.get(KnowledgeFile, 82)).status == 7


async def test_old_lease_cannot_complete_or_fail_new_claim_after_native_io(execution):
    job_id, _ = await fixtures.seed_accepted(execution.flow)

    def takeover(stage, file_id):
        if stage == "es":
            with Session(execution.flow.context.sync) as session:
                job = session.get(KnowledgeProcessingJob, job_id)
                job.lease_token = "new-owner"
                job.claim_generation += 1
                session.commit()

    execution.after_io = takeover
    assert (await run(execution, job_id))["state"] == "running"
    async with execution.flow.context.sessions() as session:
        job = await session.get(KnowledgeProcessingJob, job_id)
        assert job.lease_token == "new-owner" and job.succeeded_count == job.failed_count == 0
        assert (await session.get(KnowledgeFile, 81)).user_metadata["note"]["field_value"] == "private-value"
    assert execution.events == [("milvus", 81), ("es", 81)]


async def test_native_file_write_failure_rolls_back_item_success_in_same_transaction(execution):
    job_id, _ = await fixtures.seed_accepted(execution.flow)
    engine = execution.flow.context.engine.sync_engine
    failed = []

    def interrupt(connection, cursor, statement, parameters, context, executemany):
        if not failed and statement.lower().startswith(f"update {KnowledgeFile.__tablename__}"):
            failed.append(statement)
            raise RuntimeError("actual File SQL write rejected")

    event.listen(engine, "before_cursor_execute", interrupt)
    try:
        assert (await run(execution, job_id))["state"] == "failed"
    finally:
        event.remove(engine, "before_cursor_execute", interrupt)
    assert len(failed) == 1
    async with execution.flow.context.sessions() as session:
        job = await session.get(KnowledgeProcessingJob, job_id)
        assert job.succeeded_count == 0
        first = (await session.exec(select(KnowledgeProcessingItem).where(KnowledgeProcessingItem.file_id == 81))).one()
        assert first.state == "failed"
        assert (await session.get(KnowledgeFile, 81)).user_metadata["note"]["field_value"] == "private-value"
