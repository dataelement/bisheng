"""T737: real metadata plans, native Owners/J1 and the original ASGI routes."""

from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete
from sqlmodel import select

from bisheng.common.errcode.admin_scope import AdminScopeChangedError, AdminScopeTenantRequiredError
from bisheng.common.errcode.knowledge import KnowledgeOperationPlanChangedError, KnowledgeProcessingObsoleteError
from bisheng.knowledge.application import metadata_owner as metadata_module
from bisheng.knowledge.application import processing_owner as model_module
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan
from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
from bisheng.knowledge.domain.schemas.processing_job import (
    ProcessingCreateRequest,
    ProcessingPrecheckRequest,
    ProcessingRetryRequest,
)
from bisheng.knowledge.domain.services.processing_job_service import ProcessingJobService
from test.knowledge_unification import test_metadata_owner as fixtures
from test.knowledge_unification import test_metadata_processing_preparation as preparation
from test.knowledge_unification import test_processing_endpoints as http_fixtures
from test.knowledge_unification.test_kn_model_bindings import state as business_state

store, tenant, business, admission = fixtures.store, fixtures.tenant, fixtures.business, fixtures.admission
processing, application, metadata, owner = fixtures.processing, fixtures.application, fixtures.metadata, fixtures.owner


@pytest.fixture
async def flow(owner, monkeypatch):
    runtime = await model_module.get_knowledge_model_read_runtime()
    monkeypatch.setattr(metadata_module, "get_knowledge_model_read_runtime", AsyncMock(return_value=runtime))
    service = ProcessingJobService(owner=owner.app.owner, available_kinds={"metadata_schema_change"})
    return SimpleNamespace(
        context=owner.app.context,
        owner=owner.app.owner,
        core=owner.owner,
        service=service,
        http=http_fixtures.mount(owner.app.context, monkeypatch),
        runtime=runtime,
    )


def request():
    return ProcessingPrecheckRequest(
        kind="metadata_schema_change", parameters=preparation.parameters(preparation.rename())
    )


async def preview(flow, session):
    return await flow.service.aprecheck(session, 40, request(), identity=flow.context.user, entry_kind="web")


async def create(flow, session, plan, key="metadata-actual"):
    return await flow.service.acreate(
        session,
        40,
        ProcessingCreateRequest(
            idempotency_key=key, confirmation_id=plan.confirmation_id, plan_digest=plan.plan_digest
        ),
        identity=flow.context.user,
        entry_kind="web",
    )


async def clear_files(flow):
    async with flow.context.sessions() as session:
        for model in (KnowledgeDocumentVersion, KnowledgeDocument, KnowledgeFile):
            await session.execute(delete(model))
        await session.commit()


async def seed_accepted(flow, *, empty=False):
    """Build a real accepted ledger without pretending the public kind is assembled.

    This native fixture composes the already-delivered private Metadata Owner,
    durable confirmation repository and J1; it isolates query/worker consumers
    from the separately tested missing public precheck/create assembly.
    """
    if empty:
        await clear_files(flow)
    async with flow.context.sessions() as session:
        prepared = await flow.core.apreview(session, 40, identity=flow.context.user, parameters=request().parameters)
        actor = await metadata_module.capture_processing_actor(
            flow.context.user, space_id=40, required_action="edit", entry_kind="web"
        )
        plan = await flow.service.plans.acreate(
            session,
            operation="metadata_schema_change",
            space_id=40,
            actor_reference=actor.reference,
            targets=[item.target for item in prepared.core_plan.items],
            target_revisions=prepared.source_revisions["versions"],
            source_revisions=prepared.source_revisions,
            parameters=prepared.parameters,
            impact={},
            expires_at=flow.service.plans.clock() + timedelta(minutes=5),
        )
        accepted = await flow.core.aaccept(session, prepared, identity=flow.context.user)
        result = await flow.owner.jobs.acreate(
            session,
            space_id=40,
            kind="metadata_schema_change",
            idempotency_key="native-metadata",
            actor_user_id=accepted.actor_user_id,
            actor_reference=accepted.actor_reference,
            parameters={
                **accepted.parameters,
                "operation_id": plan.confirmation_id,
                "confirmation_id": plan.confirmation_id,
                "plan_digest": plan.plan_digest,
            },
            configuration=accepted.configuration,
            items=accepted.items,
            metadata_acceptance=accepted.metadata_acceptance,
        )
        await flow.service.plans.aconsume(
            session, plan.confirmation_id, operation_id=result.job.id, expected_digest=plan.plan_digest
        )
        await session.commit()
        return result.job.id, accepted.configuration


@pytest.mark.parametrize("empty", [False, True])
@pytest.mark.parametrize("method", ["get", "list"])
async def test_native_query_retains_manifest_after_readonly_retry_eligibility(flow, empty, method):
    job_id, _ = await seed_accepted(flow, empty=empty)
    async with flow.context.sessions() as session:
        if method == "get":
            result = await flow.service.aget(session, 40, job_id, identity=flow.context.user)
        else:
            result = (await flow.service.alist(session, 40, identity=flow.context.user)).data[0]
        assert result.id == job_id and result.total_count == (0 if empty else 2)
        assert result.hidden_item_count == (0 if empty else 1)
        assert result.state == ("succeeded" if empty else "accepted")
        assert "private-value" not in result.model_dump_json()


async def test_native_items_use_real_compact_manifest_ids_and_hide_ungranted_history(flow):
    job_id, _ = await seed_accepted(flow)
    result = await http_fixtures.call(flow.http, "GET", f"/processing-jobs/{job_id}/items?page_size=1")
    assert result["status_code"] == 200
    assert result["data"]["total"] == 1 and result["data"]["data"][0]["file_id"] == 81
    assert "hidden secret" not in str(result) and "private-value" not in str(result)


async def test_precheck_cancel_only_persists_confirmation_not_schema_files_or_job(flow):
    before = business_state(flow.context)
    async with flow.context.sessions() as session:
        values = deepcopy((await session.get(KnowledgeFile, 81)).user_metadata)
        plan = await preview(flow, session)
        assert plan.can_execute and plan.check_complete and "hidden secret" not in plan.model_dump_json()
        stored = await session.get(KnowledgeOperationPlan, plan.confirmation_id)
        assert {item["version_id"] for item in stored.target_manifest} == {181, 182}
        assert not (await session.exec(select(KnowledgeProcessingJob))).all()
        assert (await session.get(KnowledgeFile, 81)).user_metadata == values
        await session.commit()
    assert business_state(flow.context) == before


async def test_acceptance_cas_and_full_history_snapshot_share_caller_rollback(flow):
    async with flow.context.sessions() as session:
        plan = await preview(flow, session)
        await session.commit()
    async with flow.context.sessions() as session:
        before = deepcopy((await session.get(KnowledgeFile, 81)).user_metadata)
        accepted = await create(flow, session, plan)
        job = await flow.owner.jobs.aget(session, accepted.job_id)
        rows = (await session.exec(select(KnowledgeProcessingItem).order_by(KnowledgeProcessingItem.file_id))).all()
        assert [(row.file_id, row.document_id, row.version_id) for row in rows] == [(81, 80, 181), (82, 80, 182)]
        assert [row.processing_snapshot["original_status"] for row in rows] == [2, 7]
        assert (
            job.parameters["confirmation_id"] == plan.confirmation_id
            and job.parameters["plan_digest"] == plan.plan_digest
        )
        assert job.parameters["metadata_schema_revision"] == 1
        assert (await session.get(KnowledgeFile, 81)).user_metadata == before
        assert accepted.state == "accepted" and job.total_count == 2
        await session.rollback()
    async with flow.context.sessions() as session:
        root = await session.get(Knowledge, 40)
        assert (root.metadata_schema_revision, root.model_config_revision, root.index_generation, root.state) == (
            0,
            0,
            "g0",
            1,
        )
        assert not (await session.exec(select(KnowledgeProcessingJob))).all()


async def test_empty_metadata_precheck_and_accept_is_completed_structure_without_fake_item(flow):
    await clear_files(flow)
    async with flow.context.sessions() as session:
        plan = await preview(flow, session)
        assert plan.can_execute
        await session.commit()
    async with flow.context.sessions() as session:
        result = await create(flow, session, plan)
        job = await flow.owner.jobs.aget(session, result.job_id)
        assert result.state == job.state == "succeeded" and job.total_count == job.pending_count == 0
        assert job.finished_at and not job.pending_dispatch
        assert not (await session.exec(select(KnowledgeProcessingItem))).all()
        await session.commit()


async def test_manual_metadata_value_drift_after_confirmation_rejects_before_schema_acceptance(flow):
    async with flow.context.sessions() as session:
        plan = await preview(flow, session)
        await session.commit()
    async with flow.context.sessions() as session:
        (await session.get(KnowledgeFile, 81)).user_metadata = {"note": {"field_value": "manual change"}}
        await session.commit()
    async with flow.context.sessions() as session:
        with pytest.raises(KnowledgeOperationPlanChangedError):
            await create(flow, session, plan)
        await session.rollback()
    async with flow.context.sessions() as session:
        assert (await session.get(Knowledge, 40)).metadata_schema_revision == 0


@pytest.mark.parametrize("changed", ["schema", "model", "generation"])
async def test_retry_commits_actual_configuration_obsolete_before_returning_business_error(flow, changed):
    job_id, configuration = await seed_accepted(flow)
    async with flow.context.sessions() as session:
        lease = await flow.owner.jobs.aclaim(session, job_id, configuration=configuration)
        for _ in range(2):
            claimed = await flow.owner.jobs.aclaim_next_item(session, lease, configuration=configuration)
            await flow.owner.jobs.acomplete_item(
                session, claimed.lease, configuration=configuration, succeeded=False, error_code=10915
            )
        job = await flow.owner.jobs.afinalize(session, lease, configuration=configuration)
        revision = job.revision
        root = await session.get(Knowledge, 40)
        if changed == "schema":
            root.metadata_schema_revision += 2
        elif changed == "model":
            root.model_config_revision += 1
        else:
            root.index_generation = "different-generation"
        await session.commit()
    async with flow.context.sessions() as session:
        outcome = await flow.service.aretry(
            session,
            40,
            job_id,
            ProcessingRetryRequest(idempotency_key="actual-retry", expected_job_revision=revision),
            identity=flow.context.user,
            entry_kind="web",
        )
        assert isinstance(outcome.error, KnowledgeProcessingObsoleteError)
        await session.commit()
    async with flow.context.sessions() as session:
        job = await flow.owner.jobs.aget(session, job_id)
        assert job.state == "obsolete" and not job.pending_dispatch


async def test_actual_http_precheck_accept_and_queries_use_original_closed_protocol(flow):
    plan = await http_fixtures.call(
        flow.http,
        "POST",
        "/processing-jobs/precheck",
        payload=request().model_dump(mode="json"),
        headers=http_fixtures.HEADERS,
    )
    assert plan["status_code"] == 200 and plan["data"]["can_execute"]
    command = {
        "idempotency_key": "actual-http-metadata",
        "confirmation_id": plan["data"]["confirmation_id"],
        "plan_digest": plan["data"]["plan_digest"],
    }
    accepted = await http_fixtures.call(
        flow.http, "POST", "/processing-jobs", payload=command, headers=http_fixtures.HEADERS
    )
    assert accepted["status_code"] == 200 and accepted["data"]["state"] == "accepted"
    job_id = accepted["data"]["job_id"]
    detail = await http_fixtures.call(flow.http, "GET", f"/processing-jobs/{job_id}")
    assert detail["status_code"] == 200 and detail["data"]["total_count"] == 2
    assert detail["data"]["hidden_item_count"] == 1


@pytest.mark.parametrize(
    "headers,code",
    [(None, AdminScopeTenantRequiredError.Code), ({"X-Management-Tenant": "202"}, AdminScopeChangedError.Code)],
)
async def test_original_write_scope_rejects_before_metadata_plan_or_schema(flow, headers, code):
    result = await http_fixtures.call(
        flow.http, "POST", "/processing-jobs/precheck", payload=request().model_dump(mode="json"), headers=headers
    )
    assert result["status_code"] == code
    async with flow.context.sessions() as session:
        assert not (await session.exec(select(KnowledgeOperationPlan))).all()
        assert (await session.get(Knowledge, 40)).metadata_schema_revision == 0


async def test_http_rejects_after_schema_or_values_as_request_inputs(flow):
    payload = request().model_dump(mode="json")
    payload["parameters"]["after_schema"] = []
    payload["parameters"]["after_values"] = {"injected": {}}
    result = await http_fixtures.call(
        flow.http, "POST", "/processing-jobs/precheck", payload=payload, headers=http_fixtures.HEADERS
    )
    assert result["status_code"] == 422
