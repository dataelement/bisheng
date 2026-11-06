"""T677: actual ASGI/Service/Owner/SQL -> native loader/split/write path."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlmodel import Session, select

from bisheng.api.v1.schemas import FileProcessBase
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.knowledge.application import processing_identity
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
from bisheng.sensitive_word.domain.schemas import SensitiveWordCheckResult, SensitiveWordHit
from bisheng.worker.knowledge import file_worker as native
from bisheng.worker.knowledge import processing_jobs as worker
from test.knowledge_unification import test_file_worker as fixtures
from test.knowledge_unification import test_processing_endpoints as http_fixtures

store = fixtures.store
tenant = fixtures.tenant
business = fixtures.business
admission = fixtures.admission
processing = fixtures.processing
application = fixtures.application
files = fixtures.files


@pytest.fixture
async def wire(files, monkeypatch):
    async with files.context.sessions() as session:
        for ident in (81, 82):
            (await session.get(KnowledgeFile, ident)).split_rule = FileProcessBase(knowledge_id=40).model_dump_json()
        await session.commit()
    monkeypatch.setattr(worker, "get_async_db_session", files.context.sessions)
    monkeypatch.setattr(worker, "require_business_action", AsyncMock())
    monkeypatch.setattr(worker, "_active_tenant_ids", AsyncMock(return_value=[101]))
    monkeypatch.setattr(processing_identity, "resolve_web_runtime_identity", AsyncMock(return_value=files.context.user))
    monkeypatch.setattr("bisheng.permission.application.relation_api.is_tenant_admin", AsyncMock(return_value=False))
    publish = Mock()
    monkeypatch.setattr(worker.execute_processing_job, "apply_async", publish)
    return SimpleNamespace(files=files, http=http_fixtures.mount(files.context, monkeypatch), publish=publish)


async def submit(wire, kind="file_resplit", targets=None):
    request = {
        "kind": kind,
        "targets": targets or [{"file_id": 82, "version_id": 182}],
        "parameters": {
            "overrides": {
                "document": {
                    "split_mode": "custom",
                    "chunk_size": 12,
                    "chunk_overlap": 0,
                    "separator": [" "],
                    "separator_rule": ["after"],
                }
            }
        },
    }
    plan = await http_fixtures.call(
        wire.http, "POST", "/processing-jobs/precheck", payload=request, headers=http_fixtures.HEADERS
    )
    assert plan["status_code"] == 200 and plan["data"]["impact"]["overwrite_manual_chunks"]
    accepted = await http_fixtures.call(
        wire.http,
        "POST",
        "/processing-jobs",
        payload={
            "idempotency_key": "wire-file",
            "confirmation_id": plan["data"]["confirmation_id"],
            "plan_digest": plan["data"]["plan_digest"],
        },
        headers=http_fixtures.HEADERS,
    )
    assert accepted["status_code"] == 200 and accepted["data"]["state"] == "accepted"
    return accepted["data"]["job_id"]


async def detail(wire, job_id):
    result = await http_fixtures.call(wire.http, "GET", f"/processing-jobs/{job_id}")
    assert result["status_code"] == 200
    return result["data"]


@pytest.mark.parametrize("kind", ["file_reprocess", "file_resplit"])
async def test_http_reaches_actual_selected_historical_version_pipeline_and_current_model(wire, kind):
    job_id = await submit(wire, kind)
    assert worker.PROCESSING_HANDLERS[kind] is native.prepare_processing_file
    assert await worker._dispatch_pending_processing_jobs() == 1
    payload = wire.publish.call_args.kwargs["kwargs"]
    assert set(payload) == {"job_id", "expected_dispatch_revision"} and payload["job_id"] == job_id
    assert (await worker._execute_processing_job(**payload))["state"] == "succeeded"
    result = await detail(wire, job_id)
    assert result["succeeded_count"] == result["total_count"] == 1 and result["pending_count"] == 0
    assert {doc.metadata["document_id"] for doc in wire.files.vector.add_documents.call_args.args[0]} == {82}
    wire.files.vector.col.drop.assert_not_called()
    async with wire.files.context.sessions() as session:
        job = (await session.exec(select(KnowledgeProcessingJob))).one()
        root = await session.get(Knowledge, 40)
        assert (
            root.model_config_revision == job.expected_model_config_revision == job.accepted_model_config_revision == 0
        )
        assert root.index_generation == "g0" and root.model_transition is None and root.state == 1
        assert (await session.get(KnowledgeFile, 81)).status == 2
        assert (await session.get(KnowledgeFile, 82)).object_name == "source/82.txt"
        versions = (await session.exec(select(KnowledgeDocumentVersion))).all()
        assert len(versions) == 2 and not (await session.get(KnowledgeDocumentVersion, 182)).is_primary
    previous = wire.files.vector.add_documents.call_count
    await worker._execute_processing_job(**payload)
    assert wire.files.vector.add_documents.call_count == previous


async def test_actual_partial_failure_http_retry_preserves_success_and_original_effective_rule(wire):
    def ingest(documents):
        if documents[0].metadata["document_id"] == 82:
            raise RuntimeError("temporary file provider failure")

    wire.files.vector.add_documents.side_effect = ingest
    job_id = await submit(wire, targets=[{"file_id": 81, "version_id": 181}, {"file_id": 82, "version_id": 182}])
    start = await detail(wire, job_id)
    assert (await worker._execute_processing_job(job_id, start["revision"]))["state"] == "partial_failed"
    failed = await detail(wire, job_id)
    assert failed["retryable"] and failed["failed_count"] == 1 and failed["succeeded_count"] == 1
    settings = await http_fixtures.call(wire.http, "GET", "/processing-settings")
    defaults = settings["data"]["effective_defaults"]
    defaults["document"]["chunk_size"] = 900
    changed = await http_fixtures.call(
        wire.http,
        "PUT",
        "/processing-settings",
        payload={"expected_config_version": 0, "defaults": defaults},
        headers=http_fixtures.HEADERS,
    )
    assert changed["status_code"] == 200
    retry = await http_fixtures.call(
        wire.http,
        "POST",
        f"/processing-jobs/{job_id}/retry",
        payload={"idempotency_key": "wire-retry", "expected_job_revision": failed["revision"]},
        headers=http_fixtures.HEADERS,
    )
    assert retry["status_code"] == 200
    wire.files.vector.add_documents.side_effect = None
    state = await detail(wire, job_id)
    assert (await worker._execute_processing_job(job_id, state["revision"]))["state"] == "succeeded"
    async with wire.files.context.sessions() as session:
        items = (await session.exec(select(KnowledgeProcessingItem).order_by(KnowledgeProcessingItem.file_id))).all()
        assert [item.attempt for item in items] == [1, 2]
        assert {item.processing_snapshot["effective_processing"]["effective_rule"]["chunk_size"] for item in items} == {
            12
        }
        assert items[0].result["chunk_count"] == items[1].result["chunk_count"] > 1
    assert wire.files.vector.add_documents.call_count == 3
    wire.files.vector.col.drop.assert_not_called()


async def test_revoked_credential_preclaim_fails_queue_then_new_authorized_retry_recovers(wire, monkeypatch):
    job_id = await submit(wire)
    initial = await detail(wire, job_id)
    monkeypatch.setattr(
        processing_identity, "resolve_web_runtime_identity", AsyncMock(side_effect=PermissionDeniedError())
    )
    assert (await worker._execute_processing_job(job_id, initial["revision"]))["state"] == "failed"
    async with wire.files.context.sessions() as session:
        assert (await session.get(KnowledgeFile, 82)).status == 3
    wire.files.provider.assert_not_called()
    failed = await detail(wire, job_id)
    retry = await http_fixtures.call(
        wire.http,
        "POST",
        f"/processing-jobs/{job_id}/retry",
        payload={"idempotency_key": "new-authority", "expected_job_revision": failed["revision"]},
        headers=http_fixtures.HEADERS,
    )
    assert retry["status_code"] == 200
    monkeypatch.setattr(
        processing_identity, "resolve_web_runtime_identity", AsyncMock(return_value=wire.files.context.user)
    )
    accepted = await detail(wire, job_id)
    assert (await worker._execute_processing_job(job_id, accepted["revision"]))["state"] == "succeeded"


async def test_actual_safety_result_is_failed_item_and_violation_file(wire, monkeypatch):
    from bisheng.knowledge.rag import knowledge_file_pipeline

    monkeypatch.setattr(knowledge_file_pipeline.SensitiveWordPolicyService, "is_effective", lambda **kwargs: True)
    monkeypatch.setattr(
        knowledge_file_pipeline.SensitiveWordPolicyService,
        "check_text",
        lambda **kwargs: SensitiveWordCheckResult(enabled=True, hits=[SensitiveWordHit(word="alpha", count=1)]),
    )
    job_id = await submit(wire)
    accepted = await detail(wire, job_id)
    assert (await worker._execute_processing_job(job_id, accepted["revision"]))["state"] == "failed"
    async with wire.files.context.sessions() as session:
        assert (await session.get(KnowledgeFile, 82)).status == 7
        assert (await session.exec(select(KnowledgeProcessingItem))).one().state == "failed"
    wire.files.provider.assert_not_called()


async def test_related_configuration_change_after_real_parse_refuses_new_ingest_and_sql_finalize(wire, monkeypatch):
    actual_prepare = native.prepare_processing_file

    def change_after_prepare(*args, **kwargs):
        result = actual_prepare(*args, **kwargs)
        with Session(wire.files.context.sync) as session:
            root = session.get(Knowledge, 40)
            root.model_config_revision += 1
            session.add(root)
            session.commit()
        return result

    monkeypatch.setattr(worker, "prepare_processing_file", change_after_prepare, raising=False)
    job_id = await submit(wire)
    accepted = await detail(wire, job_id)
    assert (await worker._execute_processing_job(job_id, accepted["revision"]))["state"] == "obsolete"
    wire.files.provider.assert_not_called()
    wire.files.vector.col.delete.assert_not_called()
