"""T614: durable intent reaches the actual single-file rebuild and SQL Owner.

SQLite/Model/R2/source/scope/job/file SQL and identity context restoration are
real. Only web credential-store revalidation, FGA, broker and provider/vector
transports are isolated; the actual chunk handler is never replaced.
"""

from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlmodel import Session, select

from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.knowledge.application import model_reference_read, processing_identity, processing_owner
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.models import knowledge_file as file_module
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.schemas.processing_job import ProcessingRetryRequest
from bisheng.worker import tenant_context as workers
from bisheng.worker.knowledge import processing_jobs as module
from bisheng.worker.knowledge import rebuild_knowledge_worker as handler
from test.knowledge_unification import test_job_service as fixtures

store = fixtures.store
tenant = fixtures.tenant
business = fixtures.business
admission = fixtures.admission
processing = fixtures.processing
application = fixtures.application


@pytest.fixture
async def dispatch(application, monkeypatch):
    app = application
    clock = [datetime.now(UTC).replace(tzinfo=None)]
    app.owner.jobs.clock = lambda: clock[0]
    async with app.context.sessions() as session:
        row = await session.get(Knowledge, 40)
        row.index_name, row.collection_name = "idx40", "col40"
        plan = await fixtures.precheck(app, session)
        accepted = await fixtures.create(app, session, plan)
        job = await app.owner.jobs.aget(session, accepted.job_id)
        revision = job.revision
        await session.commit()
    runtime = await processing_owner.get_knowledge_model_read_runtime()

    @contextmanager
    def sessions():
        with Session(app.context.sync, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr(module, "get_async_db_session", app.context.sessions)
    monkeypatch.setattr(module, "_new_owner", lambda: app.owner)
    monkeypatch.setattr(module, "_active_tenant_ids", AsyncMock(return_value=[101]))
    monkeypatch.setattr(module, "require_business_action", AsyncMock())
    monkeypatch.setattr(processing_owner, "require_business_action", AsyncMock())
    monkeypatch.setattr(processing_identity, "resolve_web_runtime_identity", AsyncMock(return_value=app.context.user))
    monkeypatch.setattr("bisheng.permission.application.relation_api.is_tenant_admin", AsyncMock(return_value=False))
    monkeypatch.setattr(handler, "get_sync_db_session", sessions)
    monkeypatch.setattr(file_module, "get_sync_db_session", sessions)
    monkeypatch.setattr(model_reference_read, "_runtime", runtime)
    monkeypatch.setattr(handler, "get_knowledge_model_read_runtime_sync", lambda: runtime)
    sources = {
        ident: [
            {
                "_source": {
                    "text": f"manual {ident}/{i}",
                    "metadata": {"knowledge_id": 40, "document_id": ident, "pk": i, "manual": True},
                }
            }
            for i in range(3)
        ]
        for ident in (81, 82)
    }
    es = SimpleNamespace(client=Mock())
    es.client.indices.exists.return_value = True
    es.client.search.side_effect = lambda *, index, body, **kwargs: {
        "_scroll_id": "cursor",
        "hits": {"hits": deepcopy(sources[body["query"]["match"]["metadata.document_id"]])},
    }
    es.client.scroll.return_value = {"hits": {"hits": []}}
    vector = SimpleNamespace(col=Mock(spec=handler.Collection), add_texts=Mock())
    provider = Mock(return_value=Mock())
    monkeypatch.setattr(KnowledgeRag, "init_es_vectorstore_sync", lambda *args, **kwargs: es)
    monkeypatch.setattr(KnowledgeRag, "init_milvus_vectorstore", lambda *args, **kwargs: vector)
    monkeypatch.setattr(handler.LLMService, "get_bisheng_knowledge_embedding_sync", provider)
    publish = Mock()
    monkeypatch.setattr(module.execute_processing_job, "apply_async", publish)
    sender = SimpleNamespace(
        name=module.EXECUTE_TASK,
        request=SimpleNamespace(id="real-processing-task", headers={"tenant_id": 101}, called_directly=False),
    )
    monkeypatch.setattr(workers, "current_task", SimpleNamespace(_get_current_object=lambda: sender))
    workers.restore_tenant_context(sender=sender)
    try:
        yield SimpleNamespace(
            app=app,
            job_id=job.id,
            revision=revision,
            clock=clock,
            publish=publish,
            vector=vector,
            es=es,
            provider=provider,
            sources=sources,
            sender=sender,
        )
    finally:
        workers.reset_tenant_context(sender=sender)


async def test_real_handler_finishes_items_and_file_status_then_model_owner_once(dispatch):
    assert module.PROCESSING_HANDLERS["embedding_rebuild"] is handler.rebuild_processing_file
    assert (await module._execute_processing_job(dispatch.job_id, dispatch.revision))["state"] == "succeeded"
    async with dispatch.app.context.sessions() as session:
        job = await dispatch.app.owner.jobs.aget(session, dispatch.job_id)
        assert job.succeeded_count == 2 and job.expected_model_config_revision == 2
        assert job.accepted_model_config_revision == 1
        assert (await session.exec(select(KnowledgeFile.status).where(KnowledgeFile.id.in_((81, 82))))).all() == [2, 2]
    assert dispatch.vector.add_texts.call_count == 2
    assert {call.kwargs["model_id"] for call in dispatch.provider.call_args_list} == {11}
    dispatch.vector.col.drop.assert_called_once()
    dispatch.es.client.delete_by_query.assert_not_called()
    await module._execute_processing_job(dispatch.job_id, dispatch.revision)
    assert dispatch.vector.add_texts.call_count == 2


async def test_broker_failure_and_lost_ack_recover_committed_intent(dispatch):
    dispatch.publish.side_effect = RuntimeError("broker unavailable")
    assert await module._dispatch_pending_processing_jobs() == 0
    async with dispatch.app.context.sessions() as session:
        job = await dispatch.app.owner.jobs.aget(session, dispatch.job_id)
        assert job.pending_dispatch and job.dispatch_attempts == 1
    dispatch.clock[0] += timedelta(minutes=2)
    dispatch.publish.side_effect = None
    assert await module._dispatch_pending_processing_jobs() == 1
    message = dispatch.publish.call_args.kwargs
    assert message["kwargs"] == {"job_id": dispatch.job_id, "expected_dispatch_revision": dispatch.revision}
    assert message["headers"]["tenant_id"] == 101
    assert not any(key in message["kwargs"] for key in ("model_id", "actor_user_id", "actor_reference"))
    async with dispatch.app.context.sessions() as session:
        assert (await dispatch.app.owner.jobs.aget(session, dispatch.job_id)).pending_dispatch


async def test_partial_real_failure_keeps_source_and_retry_processes_only_failed_file(dispatch):
    def insert(*, texts, metadatas):
        if metadatas[0]["document_id"] == 82:
            raise RuntimeError("file embedding failed")

    dispatch.vector.add_texts.side_effect = insert
    assert (await module._execute_processing_job(dispatch.job_id, dispatch.revision))["state"] == "partial_failed"
    dispatch.es.client.delete_by_query.assert_not_called()
    async with dispatch.app.context.sessions() as session:
        job = await dispatch.app.owner.jobs.aget(session, dispatch.job_id)
        assert (await session.exec(select(KnowledgeFile.status).where(KnowledgeFile.id.in_((81, 82))))).all() == [2, 3]
        retry = await dispatch.app.app.aretry(
            session,
            40,
            job.id,
            ProcessingRetryRequest(idempotency_key="retry", expected_job_revision=job.revision),
            identity=dispatch.app.context.user,
            entry_kind="web",
        )
        assert retry.error is None
        assert (await session.get(Knowledge, 40)).state == 3
        revision = job.revision
        await session.commit()
    dispatch.vector.add_texts.side_effect = None
    await module._execute_processing_job(dispatch.job_id, dispatch.revision)
    assert dispatch.vector.add_texts.call_count == 2
    assert (await module._execute_processing_job(dispatch.job_id, revision))["state"] == "succeeded"
    assert dispatch.vector.add_texts.call_count == 3
    dispatch.vector.col.drop.assert_called_once()
    async with dispatch.app.context.sessions() as session:
        assert (await session.get(Knowledge, 40)).state == 1


async def test_revoked_original_credential_fails_durably_without_external_work(dispatch, monkeypatch):
    monkeypatch.setattr(
        processing_identity, "resolve_web_runtime_identity", AsyncMock(side_effect=PermissionDeniedError())
    )
    assert (await module._execute_processing_job(dispatch.job_id, dispatch.revision))["state"] == "failed"
    async with dispatch.app.context.sessions() as session:
        job = await dispatch.app.owner.jobs.aget(session, dispatch.job_id)
        assert (
            not job.pending_dispatch and job.pending_count == 0 and job.failed_count == 2 and job.succeeded_count == 0
        )
    dispatch.provider.assert_not_called()


async def test_missing_actual_worker_proof_rejects_before_job_or_provider(dispatch):
    workers.reset_tenant_context(sender=dispatch.sender)
    with pytest.raises(ResourceReferenceInvalidError):
        await module._execute_processing_job(dispatch.job_id, dispatch.revision)
    dispatch.provider.assert_not_called()
