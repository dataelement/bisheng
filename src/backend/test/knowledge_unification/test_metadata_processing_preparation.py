"""T701: immutable metadata plans and schema acceptance borrow one native TX."""

from copy import deepcopy
from dataclasses import replace

import pytest
from sqlalchemy import delete, update
from sqlmodel import select

from bisheng.common.errcode.knowledge import (
    KnowledgeMetadataFieldConflictError,
    KnowledgeMetadataFieldExistError,
    KnowledgeMetadataFieldImmutableError,
    KnowledgeMetadataFieldNotExistError,
    KnowledgeOperationPlanConflictError,
    ResourceReferenceInvalidError,
)
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
from bisheng.knowledge.domain.schemas.processing_job import MetadataSchemaParameters
from bisheng.knowledge.domain.services import metadata_processing_service as module
from bisheng.knowledge.domain.services.metadata_processing_service import MetadataProcessingService
from test.knowledge_unification import test_metadata_processing_repository as fixtures
from test.knowledge_unification.test_kn_model_bindings import state

store = fixtures.store
tenant = fixtures.tenant
business = fixtures.business
admission = fixtures.admission
processing = fixtures.processing
application = fixtures.application
metadata = fixtures.metadata


def parameters(*changes, revision=0):
    return MetadataSchemaParameters(expected_schema_revision=revision, changes=list(changes))


def add(name="fresh"):
    return {"operation": "add", "field_name": name, "field_type": "string"}


def rename(old="note", new="alias"):
    return {"operation": "rename", "field_name": old, "new_field_name": new}


def drop(name="note"):
    return {"operation": "delete", "field_name": name}


async def preview(app, session, service, *changes):
    return await service.apreview(session, 40, parameters(*(changes or (rename(),))))


async def test_preview_and_cancel_have_no_business_reference_or_file_writes(metadata, monkeypatch):
    monkeypatch.setattr(module, "metadata_change_timestamp", lambda: 100)
    before = state(metadata.context)
    service = MetadataProcessingService()
    async with metadata.context.sessions() as session:
        old_file = (await session.get(KnowledgeFile, 81)).model_dump(mode="json")
        plan = await preview(metadata, session, service)
        assert (plan.before_schema_revision, plan.after_schema_revision, plan.changed_at) == (0, 1, 100)
        assert not plan.accepted and len(plan.items) == 2
        assert plan.before_schema[0]["field_name"] == "note" and plan.after_schema[0]["field_name"] == "alias"
        item = plan.items[0]
        assert item.target.file_id == 81 and item.target.version_id == 181
        assert item.before_values["note"]["field_value"] == "private-value"
        assert item.after_values["alias"] == {"field_value": "private-value", "field_type": "string", "updated_at": 100}
        assert item.before_values_digest != item.after_values_digest
        assert len(item.source_revision) == len(plan.parameters_digest) == 64
        assert "private-value" not in repr(plan)
        assert (await session.get(KnowledgeFile, 81)).model_dump(mode="json") == old_file
        await session.commit()
    assert state(metadata.context) == before


async def test_add_clears_stale_same_named_values_without_touching_other_fields(metadata):
    async with metadata.context.sessions() as session:
        row = await session.get(KnowledgeFile, 81)
        row.user_metadata = {
            **row.user_metadata,
            "fresh": {"field_value": "old-deleted-data"},
            "other": {"field_value": [1, 2], "extra": {"kept": True}},
        }
        await session.commit()
    async with metadata.context.sessions() as session:
        plan = await preview(metadata, session, MetadataProcessingService(), add())
        item = plan.items[0]
        assert "fresh" in item.before_values and "fresh" not in item.after_values
        assert item.after_values["other"] == item.before_values["other"]
        assert item.after_values["note"] == item.before_values["note"]
        assert plan.items[1].before_values is None and plan.items[1].after_values is None


async def test_rename_missing_old_value_does_not_resurrect_stale_destination(metadata):
    async with metadata.context.sessions() as session:
        (await session.get(KnowledgeFile, 82)).user_metadata = {"alias": {"field_value": "unrelated-old-value"}}
        await session.commit()
    async with metadata.context.sessions() as session:
        plan = await preview(metadata, session, MetadataProcessingService())
        assert plan.items[1].after_values == {}


async def test_declared_batch_order_preserves_values_and_types_and_removes_only_targets(metadata, monkeypatch):
    monkeypatch.setattr(module, "metadata_change_timestamp", lambda: 200)
    async with metadata.context.sessions() as session:
        root = await session.get(Knowledge, 40)
        root.metadata_fields = [
            *root.metadata_fields,
            {"field_name": "removed", "field_type": "number", "updated_at": 5},
        ]
        row = await session.get(KnowledgeFile, 81)
        row.user_metadata = {
            **row.user_metadata,
            "removed": {"field_value": 12, "field_type": "number"},
            "other": {"x": [1]},
        }
        await session.commit()
    async with metadata.context.sessions() as session:
        plan = await preview(metadata, session, MetadataProcessingService(), rename(), drop("removed"), add())
        assert [row["field_name"] for row in plan.after_schema] == ["alias", "fresh"]
        assert "note" not in plan.items[0].after_values and "removed" not in plan.items[0].after_values
        assert plan.items[0].after_values["alias"]["field_type"] == "string"
        assert plan.items[0].after_values["other"] == {"x": [1]}


@pytest.mark.parametrize(
    "changes,error",
    [
        ([add("note")], KnowledgeMetadataFieldExistError),
        ([rename(new="note")], KnowledgeMetadataFieldExistError),
        ([rename(old="missing")], KnowledgeMetadataFieldNotExistError),
        ([drop("missing")], KnowledgeMetadataFieldNotExistError),
        ([add("document_id")], KnowledgeMetadataFieldConflictError),
        ([rename(old="document_id")], KnowledgeMetadataFieldImmutableError),
        ([drop("document_id")], KnowledgeMetadataFieldImmutableError),
        ([rename(new="document_id")], KnowledgeMetadataFieldConflictError),
        ([add(), add()], KnowledgeMetadataFieldExistError),
        ([rename(), rename(old="alias", new="second")], KnowledgeOperationPlanConflictError),
        ([drop(), add("note")], KnowledgeOperationPlanConflictError),
    ],
)
async def test_whole_batch_validation_rejects_ambiguity_and_existing_errors_before_write(metadata, changes, error):
    before = state(metadata.context)
    async with metadata.context.sessions() as session:
        with pytest.raises(error):
            await MetadataProcessingService().apreview(session, 40, parameters(*changes))
        await session.commit()
    assert state(metadata.context) == before


async def test_schema_cas_acceptance_does_not_commit_or_apply_file_values(metadata, monkeypatch):
    service = MetadataProcessingService()
    monkeypatch.setattr(module, "metadata_change_timestamp", lambda: 100)
    before = state(metadata.context)
    async with metadata.context.sessions() as session:
        old = deepcopy((await session.get(KnowledgeFile, 81)).user_metadata)
        plan = await preview(metadata, session, service)
        monkeypatch.setattr(module, "metadata_change_timestamp", lambda: 999)
        accepted = await service.aaccept(session, plan)
        assert accepted.accepted and accepted.changed_at == 100 and accepted.after_schema_revision == 1
        assert accepted.items[0].after_values["alias"]["updated_at"] == 100
        assert (await session.get(KnowledgeFile, 81)).user_metadata == old
        assert not (await session.exec(select(KnowledgeProcessingJob))).all()
        await session.rollback()
    assert state(metadata.context) == before
    async with metadata.context.sessions() as session:
        accepted = await service.aaccept(session, await preview(metadata, session, service))
        await session.commit()
    root = next(row for row in state(metadata.context)["knowledge"] if row["id"] == 40)
    assert root["metadata_fields"] == list(accepted.after_schema) and root["metadata_schema_revision"] == 1
    assert (root["model"], root["model_config_revision"], root["index_generation"], root["state"]) == ("11", 0, "g0", 1)
    async with metadata.context.sessions() as session:
        assert [(await session.get(KnowledgeFile, key)).status for key in (81, 82)] == [2, 7]


@pytest.mark.parametrize("kind", ["copy", "other_instance", "nested_schema", "nested_values", "source_values", "field"])
async def test_plan_requires_original_instance_and_detached_unchanged_issued_facts(metadata, kind):
    service = MetadataProcessingService()
    before = state(metadata.context)
    async with metadata.context.sessions() as session:
        plan = await preview(metadata, session, service)
        if kind == "copy":
            plan = replace(plan)
        elif kind == "other_instance":
            service = MetadataProcessingService()
        elif kind == "nested_schema":
            plan.after_schema[0]["field_name"] = "forged"
        elif kind == "nested_values":
            plan.items[0].after_values["alias"]["field_value"] = "forged"
        elif kind == "source_values":
            plan._scope.items[0].user_metadata["note"]["field_value"] = "forged"
        else:
            object.__setattr__(plan, "after_schema_revision", 9)
        with pytest.raises(ResourceReferenceInvalidError):
            await service.aaccept(session, plan)
        await session.rollback()
    assert state(metadata.context) == before


async def test_plan_is_consumed_once_and_cannot_cross_same_session_transaction(metadata):
    service = MetadataProcessingService()
    async with metadata.context.sessions() as session:
        plan = await preview(metadata, session, service)
        await service.aaccept(session, plan)
        with pytest.raises(ResourceReferenceInvalidError):
            await service.aaccept(session, plan)
        await session.rollback()
        # Reusing the Session object does not preserve its transaction authority.
        await session.get(Knowledge, 40)
        with pytest.raises(ResourceReferenceInvalidError):
            await service.aaccept(session, plan)


@pytest.mark.parametrize("drift", ["schema", "generation", "values", "source"])
async def test_acceptance_reloads_exact_scope_and_schema_revision(metadata, drift):
    service = MetadataProcessingService()
    async with metadata.context.sessions() as session:
        plan = await preview(metadata, session, service)
        if drift in {"schema", "generation"}:
            values = {"metadata_schema_revision": 1} if drift == "schema" else {"index_generation": "g1"}
            await session.execute(
                update(Knowledge)
                .where(Knowledge.id == 40, Knowledge.tenant_id == 101)
                .values(**values)
                .execution_options(synchronize_session=False)
            )
        else:
            values = (
                {"user_metadata": {"note": {"field_value": "new"}}} if drift == "values" else {"object_name": "new"}
            )
            await session.execute(
                update(KnowledgeFile)
                .where(KnowledgeFile.id == 81, KnowledgeFile.tenant_id == 101)
                .values(**values)
                .execution_options(synchronize_session=False)
            )
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await service.aaccept(session, plan)
        await session.rollback()


async def test_expected_schema_revision_is_a_real_precondition(metadata):
    async with metadata.context.sessions() as session:
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await MetadataProcessingService().apreview(session, 40, parameters(add(), revision=1))


async def test_real_empty_scope_saves_sql_schema_without_fabricated_items_or_job(metadata):
    async with metadata.context.sessions() as session:
        await session.execute(delete(KnowledgeDocumentVersion).where(KnowledgeDocumentVersion.document_id == 80))
        await session.execute(delete(KnowledgeDocument).where(KnowledgeDocument.knowledge_id == 40))
        await session.execute(
            delete(KnowledgeFile).where(KnowledgeFile.knowledge_id == 40, KnowledgeFile.tenant_id == 101)
        )
        await session.commit()
    service = MetadataProcessingService()
    async with metadata.context.sessions() as session:
        result = await service.aaccept(session, await preview(metadata, session, service, add()))
        assert result.items == () and result.accepted and result.after_schema_revision == 1
        assert not (await session.exec(select(KnowledgeProcessingJob))).all()
        await session.commit()
