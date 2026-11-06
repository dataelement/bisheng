"""T733: actual leased metadata items use exact native SQL and one caller TX."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event, update

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ResourceReferenceInvalidError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
from bisheng.knowledge.domain.repositories.metadata_execution_repository import MetadataExecutionRepository
from bisheng.knowledge.domain.repositories.metadata_processing_repository import metadata_digest
from bisheng.knowledge.domain.repositories.processing_job_repository import ItemLease, JobLease
from bisheng.knowledge.domain.services.metadata_processing_service import MetadataProcessingService
from test.knowledge_unification import test_metadata_processing_preparation as fixtures

store, tenant, business, admission = fixtures.store, fixtures.tenant, fixtures.business, fixtures.admission
processing, application, metadata = fixtures.processing, fixtures.application, fixtures.metadata


def snapshot(item, changes):
    return {
        "schema_version": 1,
        "mode": "metadata_schema_change",
        "target": item.target.model_dump(mode="json"),
        "parent_id": item.parent_id,
        "source_revision": item.source_revision,
        "before_values": deepcopy(item.before_values),
        "after_values": deepcopy(item.after_values),
        "before_values_digest": item.before_values_digest,
        "after_values_digest": item.after_values_digest,
        "original_status": item.original_status,
        "affected_fields": list(
            dict.fromkeys(
                name
                for change in changes
                for name in (change["field_name"], change.get("new_field_name"))
                if name is not None
            )
        ),
    }


async def seed_execution(context):
    async with context.sessions() as session:
        core = MetadataProcessingService()
        plan = await core.apreview(session, 40, fixtures.parameters(fixtures.rename()))
        accepted = await core.aaccept(session, plan)
        now = datetime.utcnow()
        job = KnowledgeProcessingJob(
            id="metadata-job",
            tenant_id=101,
            space_id=40,
            kind="metadata_schema_change",
            state="running",
            actor_user_id=7,
            actor_reference={"actor_id": 7},
            idempotency_key="metadata-job",
            request_hash="a" * 64,
            parameters={
                "metadata_schema_revision": accepted.after_schema_revision,
                "metadata_schema_digest": metadata_digest(accepted.after_schema),
                "after_schema": list(accepted.after_schema),
                "changed_at": accepted.changed_at,
            },
            expected_model_config_revision=accepted.model_config_revision,
            accepted_model_config_revision=accepted.model_config_revision,
            expected_index_generation=accepted.index_generation,
            total_count=len(accepted.items),
            pending_count=len(accepted.items),
            claim_generation=1,
            lease_token="job-token",
            lease_until=now + timedelta(minutes=15),
            pending_dispatch=False,
        )
        rows = []
        for prepared in accepted.items:
            rows.append(
                KnowledgeProcessingItem(
                    id=f"item-{prepared.target.file_id}",
                    tenant_id=101,
                    job_id=job.id,
                    **prepared.target.model_dump(),
                    expected_space_id=40,
                    expected_parent_id=prepared.parent_id,
                    processing_snapshot=snapshot(prepared, accepted.changes),
                    state="running",
                    attempt=1,
                    claim_generation=1,
                    lease_token=f"item-token-{prepared.target.file_id}",
                    lease_until=job.lease_until,
                )
            )
        job.scope_manifest = [
            {
                **row.processing_snapshot["target"],
                "expected_space_id": 40,
                "expected_parent_id": row.expected_parent_id,
                "processing_snapshot": deepcopy(row.processing_snapshot),
            }
            for row in rows
        ]
        session.add(job)
        session.add_all(rows)
        await session.commit()
    return SimpleNamespace(context=context, job_id=job.id, item_id=rows[0].id, accepted=accepted)


@pytest.fixture
async def execution(metadata):
    return await seed_execution(metadata.context)


async def loaded(session, execution):
    return await session.get(KnowledgeProcessingJob, execution.job_id), await session.get(
        KnowledgeProcessingItem, execution.item_id
    )


def lease(job, item):
    return ItemLease(
        JobLease(job.id, job.lease_token, job.claim_generation, job.lease_until),
        item.id,
        item.lease_token,
        item.claim_generation,
        item.lease_until,
    )


async def test_actual_root_configuration_is_fresh_scalar_schema_evidence(execution):
    async with execution.context.sessions() as session, session.begin():
        repo = MetadataExecutionRepository()
        before = await repo.aread_configuration(session, 40)
        assert (before.model_config_revision, before.index_generation, before.metadata_schema_revision) == (0, "g0", 1)
        assert before.metadata_schema_digest == metadata_digest(execution.accepted.after_schema)
        with pytest.raises(FrozenInstanceError):
            before.metadata_schema_revision = 3
        await session.execute(update(Knowledge).where(Knowledge.id == 40).values(metadata_schema_revision=3))
        after = await repo.aread_configuration(session, 40)
        assert after.metadata_schema_revision == 3 and after.metadata_schema_digest == before.metadata_schema_digest


async def test_exact_item_detaches_values_and_accepts_only_frozen_before_or_after(execution):
    async with execution.context.sessions() as session:
        job, item = await loaded(session, execution)
        repo = MetadataExecutionRepository()
        result = await repo.aread_item(session, job, item)
        assert result.target.file_id == 81 and result.parent_id is None and result.original_status == 2
        assert result.after_values == execution.accepted.items[0].after_values
        assert "private-value" not in repr(result)
        result.after_values["alias"]["field_value"] = "detached"
        assert (await repo.aread_item(session, job, item)).after_values != result.after_values
        (await session.get(KnowledgeFile, 81)).user_metadata = deepcopy(execution.accepted.items[0].after_values)
        await session.flush()
        assert (await repo.aread_item(session, job, item)).source_revision == result.source_revision


@pytest.mark.parametrize("status", [2, 3, 6, 7])
async def test_original_terminal_file_statuses_are_preserved(execution, status):
    async with execution.context.sessions() as session:
        (await session.get(KnowledgeFile, 81)).status = status
        await session.commit()
    async with execution.context.sessions() as session:
        job, item = await loaded(session, execution)
        assert await MetadataExecutionRepository().awrite_values(session, job, item, lease=lease(job, item))
        assert (await session.get(KnowledgeFile, 81)).status == status
        assert item.state == "succeeded" and job.succeeded_count == 1
        await session.rollback()
    async with execution.context.sessions() as session:
        assert (await session.get(KnowledgeFile, 81)).user_metadata == execution.accepted.items[0].before_values
        assert (await session.get(KnowledgeProcessingItem, execution.item_id)).state == "running"


@pytest.mark.parametrize(
    "broken",
    [
        "foreign_file",
        "moved",
        "directory",
        "document",
        "version",
        "duplicate",
        "primary",
        "parent",
        "source",
        "values",
        "status1",
        "status4",
        "status5",
        "snapshot",
    ],
)
async def test_precise_physical_or_frozen_chain_drift_rejected(execution, broken):
    async with execution.context.sessions() as session:
        row = await session.get(KnowledgeFile, 81)
        if broken == "foreign_file":
            row.tenant_id = 202
        elif broken == "moved":
            row.knowledge_id = 999
        elif broken == "directory":
            row.file_type = 0
        elif broken == "document":
            (await session.get(KnowledgeDocument, 80)).knowledge_id = 999
        elif broken == "version":
            (await session.get(KnowledgeDocumentVersion, 181)).knowledge_file_id = 82
        elif broken == "duplicate":
            session.add(KnowledgeDocumentVersion(id=999, document_id=80, knowledge_file_id=81, version_no=3))
        elif broken == "primary":
            (await session.get(KnowledgeDocument, 80)).primary_version_id = 999
        elif broken == "parent":
            row.file_level_path = "/90"
        elif broken == "source":
            row.object_name = "replaced"
        elif broken == "values":
            row.user_metadata = {"manual": {"field_value": "drift"}}
        elif broken.startswith("status"):
            row.status = int(broken[-1])
        else:
            item = await session.get(KnowledgeProcessingItem, execution.item_id)
            item.processing_snapshot = {**item.processing_snapshot, "after_values": {"forged": {}}}
        with bypass_tenant_filter():
            await session.commit()
    async with execution.context.sessions() as session:
        job, item = await loaded(session, execution)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await MetadataExecutionRepository().aread_item(session, job, item)


async def test_stale_lease_cannot_write_values_or_complete_item(execution):
    async with execution.context.sessions() as session:
        job, item = await loaded(session, execution)
        stale = replace(lease(job, item), claim_generation=0)
        assert not await MetadataExecutionRepository().awrite_values(session, job, item, lease=stale)
        assert (
            item.state == "running"
            and (await session.get(KnowledgeFile, 81)).user_metadata == execution.accepted.items[0].before_values
        )


async def test_unrelated_pending_file_remark_remains_owned_by_caller(execution):
    async with execution.context.sessions() as session:
        job, item = await loaded(session, execution)
        row = await session.get(KnowledgeFile, 81)
        row.remark = "pending unrelated note"
        assert await MetadataExecutionRepository().awrite_values(session, job, item, lease=lease(job, item))
        await session.commit()
    async with execution.context.sessions() as session:
        assert (await session.get(KnowledgeFile, 81)).remark == "pending unrelated note"


@pytest.mark.parametrize("pending", ["root", "values", "version", "new_duplicate"])
async def test_pending_critical_target_change_rejected_before_flush(execution, pending):
    async with execution.context.sessions() as session:
        job, item = await loaded(session, execution)
        if pending == "root":
            (await session.get(Knowledge, 40)).metadata_schema_revision = 99
        elif pending == "values":
            (await session.get(KnowledgeFile, 81)).user_metadata = {"manual": {}}
        elif pending == "version":
            (await session.get(KnowledgeDocumentVersion, 181)).knowledge_file_id = 82
        else:
            session.add(KnowledgeDocumentVersion(document_id=80, knowledge_file_id=81, version_no=3))
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await MetadataExecutionRepository().awrite_values(session, job, item, lease=lease(job, item))
        await session.rollback()
    async with execution.context.sessions() as session:
        assert (await session.get(Knowledge, 40)).metadata_schema_revision == 1
        assert (await session.get(KnowledgeFile, 81)).user_metadata == execution.accepted.items[0].before_values
        assert (await session.get(KnowledgeDocumentVersion, 181)).knowledge_file_id == 81


@pytest.mark.parametrize("pending", ["existing_other_version", "historical_primary_file"])
async def test_pending_related_version_or_primary_payload_rejected_before_completion(execution, pending):
    async with execution.context.sessions() as session:
        job, item = await loaded(session, execution)
        if pending == "existing_other_version":
            (await session.get(KnowledgeDocumentVersion, 182)).knowledge_file_id = 81
        else:
            item = await session.get(KnowledgeProcessingItem, "item-82")
            (await session.get(KnowledgeFile, 81)).knowledge_id = 999
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await MetadataExecutionRepository().awrite_values(session, job, item, lease=lease(job, item))
        await session.rollback()
    async with execution.context.sessions() as session:
        assert (await session.get(KnowledgeDocumentVersion, 182)).knowledge_file_id == 82
        assert (await session.get(KnowledgeFile, 81)).knowledge_id == 40
        job = await session.get(KnowledgeProcessingJob, execution.job_id)
        assert job.succeeded_count == 0


async def test_unrelated_primary_payload_remark_is_not_a_chain_mutation(execution):
    async with execution.context.sessions() as session:
        job, _ = await loaded(session, execution)
        item = await session.get(KnowledgeProcessingItem, "item-82")
        (await session.get(KnowledgeFile, 81)).remark = "caller-owned primary note"
        assert await MetadataExecutionRepository().awrite_values(session, job, item, lease=lease(job, item))
        await session.commit()
    async with execution.context.sessions() as session:
        assert (await session.get(KnowledgeFile, 81)).remark == "caller-owned primary note"


async def test_completion_refusal_cannot_leave_file_values_written(execution):
    async with execution.context.sessions() as session:
        job, item = await loaded(session, execution)
        repo = MetadataExecutionRepository()
        repo.jobs.acomplete_item = AsyncMock(return_value=False)
        assert not await repo.awrite_values(session, job, item, lease=lease(job, item))
        assert (await session.get(KnowledgeFile, 81)).user_metadata == execution.accepted.items[0].before_values


async def test_values_and_item_completion_share_external_rollback(execution):
    async with execution.context.sessions() as session:
        job, item = await loaded(session, execution)
        source = deepcopy((await session.get(KnowledgeFile, 81)).model_dump())
        assert await MetadataExecutionRepository().awrite_values(session, job, item, lease=lease(job, item))
        row = (await session.get(KnowledgeFile, 81)).model_dump()
        assert row == {**source, "user_metadata": execution.accepted.items[0].after_values}
        await session.commit()
    async with execution.context.sessions() as session:
        assert (await session.get(KnowledgeProcessingItem, execution.item_id)).state == "succeeded"
        assert (await session.get(Knowledge, 40)).model_config_revision == 0


async def test_native_transaction_and_concrete_tenant_required(execution):
    repo = MetadataExecutionRepository()
    with pytest.raises(TypeError):
        await repo.aread_configuration(object(), 40)
    async with execution.context.sessions() as session:
        with pytest.raises(ResourceReferenceInvalidError):
            await repo.aread_configuration(session, 40)
        await session.begin()
        with bypass_tenant_filter(), pytest.raises(ResourceReferenceInvalidError):
            await repo.aread_configuration(session, 40)


async def test_guard_queries_are_exact_pk_and_constant_for_401_versions(metadata):
    async with metadata.context.sessions() as session:
        for number in range(399):
            ident = 1000 + number
            session.add(KnowledgeFile(id=ident, tenant_id=101, knowledge_id=40, file_name=f"history-{ident}", status=3))
            session.add(
                KnowledgeDocumentVersion(id=ident, document_id=80, knowledge_file_id=ident, version_no=number + 3)
            )
        await session.commit()
    execution = await seed_execution(metadata.context)
    selects = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().startswith("SELECT"):
            selects.append(statement)

    event.listen(metadata.context.engine.sync_engine, "before_cursor_execute", capture)
    try:
        async with execution.context.sessions() as session:
            job, item = await loaded(session, execution)
            selects.clear()
            for _ in range(10):
                await MetadataExecutionRepository().aread_item(session, job, item)
        assert len(selects) <= 50
        assert all(
            "knowledge_document_version.id =" in query
            for query in selects
            if "JOIN knowledge_document_version" in query
        )
    finally:
        event.remove(metadata.context.engine.sync_engine, "before_cursor_execute", capture)
