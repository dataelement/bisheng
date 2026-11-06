"""T735: actual metadata Owner binds authorization, private plans and SQL CAS."""

from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete
from sqlmodel import select

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ResourceReferenceInvalidError
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.knowledge.application import metadata_owner as module
from bisheng.knowledge.application.metadata_owner import MetadataProcessingOwner
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
from bisheng.knowledge.domain.repositories.metadata_processing_repository import metadata_digest
from test.knowledge_unification import test_metadata_processing_preparation as fixtures

store, tenant, business, admission = fixtures.store, fixtures.tenant, fixtures.business, fixtures.admission
processing, application, metadata = fixtures.processing, fixtures.application, fixtures.metadata


@pytest.fixture
def owner(metadata, monkeypatch):
    auth = AsyncMock()
    monkeypatch.setattr(module, "require_business_action", auth)
    return SimpleNamespace(app=metadata, owner=MetadataProcessingOwner(), auth=auth)


async def preview(fixture, session):
    return await fixture.owner.apreview(
        session, 40, identity=fixture.app.context.user, parameters=fixtures.parameters(fixtures.rename())
    )


async def accept(fixture, session, plan):
    return await fixture.owner.aaccept(session, plan, identity=fixture.app.context.user)


async def create(fixture, session, accepted, key="metadata-request", **overrides):
    kwargs = {
        "space_id": 40,
        "kind": "metadata_schema_change",
        "idempotency_key": key,
        "actor_user_id": accepted.actor_user_id,
        "actor_reference": accepted.actor_reference,
        "parameters": accepted.parameters,
        "configuration": accepted.configuration,
        "items": accepted.items,
        "metadata_acceptance": accepted.metadata_acceptance,
    }
    return await fixture.owner.jobs.acreate(session, **{**kwargs, **overrides})


async def clear_files(fixture):
    async with fixture.app.context.sessions() as session:
        for model in (KnowledgeDocumentVersion, KnowledgeDocument, KnowledgeFile):
            await session.execute(delete(model))
        await session.commit()


async def test_real_preview_and_accept_keep_rg_file_values_and_references_in_original_transaction(owner):
    async with owner.app.context.sessions() as session:
        before_file = deepcopy((await session.get(KnowledgeFile, 81)).model_dump())
        plan = await preview(owner, session)
        assert (plan.configuration.model_config_revision, plan.configuration.index_generation) == (0, "g0")
        assert plan.configuration.metadata_schema_revision == 1
        assert plan.source_revisions["metadata_schema_revision"] == 0
        assert len(plan.source_revisions["versions"]) == 2
        assert (await session.get(Knowledge, 40)).metadata_schema_revision == 0
        accepted = await accept(owner, session, plan)
        assert len(accepted.items) == 2 and accepted.metadata_acceptance is None
        assert accepted.parameters["metadata_schema_revision"] == 1
        assert accepted.parameters["metadata_schema_digest"] == metadata_digest(accepted.parameters["after_schema"])
        assert accepted.configuration.metadata_schema_digest == accepted.parameters["metadata_schema_digest"]
        assert accepted.parameters["request_parameters"] == fixtures.parameters(fixtures.rename()).model_dump(
            mode="json"
        )
        assert all(value.processing_snapshot["mode"] == "metadata_schema_change" for value in accepted.items)
        assert (await session.get(KnowledgeFile, 81)).model_dump() == before_file
        result = await create(owner, session, accepted)
        assert result.job.state == "accepted" and result.job.pending_dispatch and result.job.total_count == 2
        await session.rollback()
    async with owner.app.context.sessions() as session:
        assert (await session.get(Knowledge, 40)).metadata_schema_revision == 0
        assert not (await session.exec(select(KnowledgeProcessingJob))).all()
    assert owner.auth.await_count >= 2
    assert all(
        call.kwargs == {"resource_type": "knowledge_space", "resource_id": 40, "action": "edit"}
        for call in owner.auth.await_args_list
    )


@pytest.mark.parametrize("tamper", ["copy", "parameters", "source", "core"])
async def test_private_same_transaction_plan_cannot_be_forged_or_mutated(owner, tamper):
    async with owner.app.context.sessions() as session:
        plan = await preview(owner, session)
        if tamper == "copy":
            plan = replace(plan)
        elif tamper == "parameters":
            plan.parameters["changes"][0]["new_field_name"] = "forged"
        elif tamper == "source":
            plan.source_revisions["versions"].clear()
        else:
            plan.core_plan.items[0].after_values["alias"]["field_value"] = "forged"
        with pytest.raises(ResourceReferenceInvalidError):
            await accept(owner, session, plan)
        await session.rollback()


async def test_plan_is_not_reusable_after_transaction_or_session_changes(owner):
    async with owner.app.context.sessions() as session:
        plan = await preview(owner, session)
        await session.commit()
        await session.begin()
        with pytest.raises(ResourceReferenceInvalidError):
            await accept(owner, session, plan)
    async with owner.app.context.sessions() as session, session.begin():
        with pytest.raises(ResourceReferenceInvalidError):
            await accept(owner, session, plan)


async def test_auth_is_rechecked_before_acceptance_and_no_audit_id_becomes_identity(owner):
    async with owner.app.context.sessions() as session:
        with pytest.raises(PermissionDeniedError):
            await owner.owner.apreview(
                session, 40, identity=SimpleNamespace(user_id=7), parameters=fixtures.parameters(fixtures.rename())
            )
        plan = await preview(owner, session)
        owner.auth.side_effect = PermissionDeniedError()
        with pytest.raises(PermissionDeniedError):
            await accept(owner, session, plan)
        await session.rollback()


async def test_same_session_source_drift_rejects_before_schema_cas(owner):
    async with owner.app.context.sessions() as session:
        plan = await preview(owner, session)
        (await session.get(KnowledgeFile, 81)).object_name = "changed"
        await session.flush()
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await accept(owner, session, plan)
        await session.rollback()


async def test_empty_schema_change_is_actual_completed_zero_item_record_and_rolls_back_together(owner):
    await clear_files(owner)
    async with owner.app.context.sessions() as session:
        plan = await preview(owner, session)
        accepted = await accept(owner, session, plan)
        assert accepted.items == () and accepted.metadata_acceptance is not None
        result = await create(owner, session, accepted)
        job = result.job
        assert job.state == "succeeded" and job.total_count == job.pending_count == job.succeeded_count == 0
        assert not job.pending_dispatch and job.finished_at is not None
        assert not (await session.exec(select(KnowledgeProcessingItem))).all()
        assert await owner.owner.jobs.aclaim(session, job.id, configuration=accepted.configuration) is None
        again = await create(owner, session, accepted)
        assert again.reused and again.job.id == job.id
        await session.rollback()
    async with owner.app.context.sessions() as session:
        assert (await session.get(Knowledge, 40)).metadata_schema_revision == 0
        assert not (await session.exec(select(KnowledgeProcessingJob))).all()


async def test_empty_owner_does_not_admit_or_construct_a_model_provider(owner, monkeypatch):
    await clear_files(owner)
    deny = AsyncMock(side_effect=AssertionError("empty schema change has no model execution"))
    monkeypatch.setattr(owner.owner.model_owner, "aread_current", deny)
    async with owner.app.context.sessions() as session:
        accepted = await accept(owner, session, await preview(owner, session))
        assert (await create(owner, session, accepted)).job.state == "succeeded"
        deny.assert_not_awaited()


@pytest.mark.parametrize("tamper", ["dict", "copy", "actor", "schema", "parameters", "replay"])
async def test_empty_completion_receipt_is_original_context_bound_and_one_use(owner, tamper):
    await clear_files(owner)
    async with owner.app.context.sessions() as session:
        accepted = await accept(owner, session, await preview(owner, session))
        receipt = accepted.metadata_acceptance
        kwargs = {}
        if tamper == "dict":
            kwargs["metadata_acceptance"] = {"space_id": 40}
        elif tamper == "copy":
            kwargs["metadata_acceptance"] = replace(receipt)
        elif tamper == "actor":
            kwargs["actor_reference"] = {"actor_id": 999}
        elif tamper == "schema":
            (await session.get(Knowledge, 40)).metadata_schema_revision = 99
        elif tamper == "parameters":
            accepted.parameters["after_schema"].clear()
        else:
            await create(owner, session, accepted)
        with pytest.raises(ResourceReferenceInvalidError):
            await create(owner, session, accepted, key="other-request", **kwargs)
        await session.rollback()


async def test_empty_completion_receipt_cannot_cross_native_transaction(owner):
    await clear_files(owner)
    async with owner.app.context.sessions() as session:
        accepted = await accept(owner, session, await preview(owner, session))
        await session.commit()
        await session.begin()
        with pytest.raises(ResourceReferenceInvalidError):
            await create(owner, session, accepted)
