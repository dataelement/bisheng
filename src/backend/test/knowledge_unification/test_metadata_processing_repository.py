"""T699: complete native metadata scope, tenant isolation and schema-only CAS."""

from dataclasses import FrozenInstanceError
from unittest.mock import patch

import pytest
from sqlalchemy import delete, event, update
from sqlmodel import select

from bisheng.common.errcode.knowledge import (
    KnowledgeOperationPlanConflictError,
    KnowledgeProcessingConflictError,
    ResourceReferenceInvalidError,
)
from bisheng.common.errcode.knowledge_space import SpaceNotFoundError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
from bisheng.knowledge.domain.repositories.metadata_processing_repository import MetadataProcessingRepository
from bisheng.knowledge.domain.repositories.processing_job_repository import NewProcessingItem, ProcessingConfiguration
from bisheng.knowledge.domain.schemas.processing_job import ResourceVersionTarget
from test.knowledge_unification import test_job_service as fixtures

store = fixtures.store
tenant = fixtures.tenant
business = fixtures.business
admission = fixtures.admission
processing = fixtures.processing
application = fixtures.application

SCHEMA = [{"field_name": "note", "field_type": "string", "updated_at": 10}]


@pytest.fixture
async def metadata(application):
    async with application.context.sessions() as session:
        root = await session.get(Knowledge, 40)
        root.metadata_fields = SCHEMA
        first, second = await session.get(KnowledgeFile, 81), await session.get(KnowledgeFile, 82)
        first.object_name = "source/first.txt"
        first.user_metadata = {"note": {"field_value": "private-value", "field_type": "string", "updated_at": 10}}
        second.status = 7
        await session.commit()
    return application


async def test_full_scope_has_real_version_source_and_separate_private_values(metadata):
    async with metadata.context.sessions() as session:
        scope = await MetadataProcessingRepository().aload_scope(session, 40)
        assert (scope.tenant_id, scope.space_id, scope.schema_revision) == (101, 40, 0)
        assert scope.schema_fields == tuple(SCHEMA)
        assert (scope.model_config_revision, scope.index_generation) == (0, "g0")
        assert [(item.target.file_id, item.target.document_id, item.target.version_id) for item in scope.items] == [
            (81, 80, 181),
            (82, 80, 182),
        ]
        assert [item.status for item in scope.items] == [2, 7]
        assert all(len(item.source_revision) == 64 for item in scope.items)
        assert scope.items[0].parent_id is None
        assert "private-value" not in repr(scope)
        with pytest.raises(FrozenInstanceError):
            scope.schema_revision = 9
        scope.items[0].user_metadata["note"]["field_value"] = "detached"
        assert (await session.get(KnowledgeFile, 81)).user_metadata["note"]["field_value"] == "private-value"


async def test_value_changes_are_separate_from_physical_source_revision(metadata):
    repo = MetadataProcessingRepository()
    async with metadata.context.sessions() as session:
        first = await repo.aload_scope(session, 40)
        row = await session.get(KnowledgeFile, 81)
        row.user_metadata = {"note": {"field_value": "changed", "field_type": "string"}}
        await session.flush()
        changed = await repo.aload_scope(session, 40)
        assert changed.items[0].source_revision == first.items[0].source_revision
        assert changed.items[0].values_revision != first.items[0].values_revision
        assert changed.items[0].user_metadata != first.items[0].user_metadata
        row.object_name = "replaced-source"
        await session.flush()
        assert (await repo.aload_scope(session, 40)).items[0].source_revision != first.items[0].source_revision


async def test_no_autoflush_and_fresh_columns_do_not_discard_identity_map_work(metadata):
    async with metadata.context.sessions() as session:
        root, cached = await session.get(Knowledge, 40), await session.get(KnowledgeFile, 81)
        pending = KnowledgeFile(tenant_id=101, knowledge_id=40, file_name="not-flushed", status=5)
        session.add(pending)
        with session.no_autoflush:
            await session.execute(
                update(Knowledge)
                .where(Knowledge.id == 40, Knowledge.tenant_id == 101)
                .values(metadata_schema_revision=4)
                .execution_options(synchronize_session=False)
            )
            await session.execute(
                update(KnowledgeFile)
                .where(KnowledgeFile.id == 81, KnowledgeFile.tenant_id == 101)
                .values(status=3)
                .execution_options(synchronize_session=False)
            )
        scope = await MetadataProcessingRepository().aload_scope(session, 40, for_update=True)
        assert scope.schema_revision == 4 and scope.items[0].status == 3
        assert root.metadata_schema_revision == 0 and cached.status == 2 and pending.id is None
        await session.rollback()


@pytest.mark.parametrize("broken", ["schema", "values"])
async def test_invalid_saved_json_shape_is_not_treated_as_empty(metadata, broken):
    async with metadata.context.sessions() as session:
        if broken == "schema":
            await session.execute(
                update(Knowledge).where(Knowledge.id == 40, Knowledge.tenant_id == 101).values(metadata_fields={})
            )
        else:
            await session.execute(
                update(KnowledgeFile)
                .where(KnowledgeFile.id == 81, KnowledgeFile.tenant_id == 101)
                .values(user_metadata=[])
            )
        await session.commit()
    async with metadata.context.sessions() as session:
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await MetadataProcessingRepository().aload_scope(session, 40)


@pytest.mark.parametrize(
    "broken",
    [
        "unversioned",
        "empty_document",
        "missing_file",
        "foreign_file",
        "foreign_directory",
        "foreign_space",
        "duplicate_file",
        "orphan_directory",
        "primary",
        "multiple_primary",
        "missing_primary",
    ],
)
async def test_incomplete_physical_or_logical_scope_never_becomes_empty(metadata, broken):
    async with metadata.context.sessions() as session:
        if broken == "unversioned":
            session.add(KnowledgeFile(id=90, tenant_id=101, knowledge_id=40, file_name="orphan", status=3))
        elif broken == "empty_document":
            session.add(KnowledgeDocument(id=90, knowledge_id=40))
        elif broken == "missing_file":
            await session.execute(delete(KnowledgeFile).where(KnowledgeFile.id == 81, KnowledgeFile.tenant_id == 101))
        elif broken == "foreign_file":
            (await session.get(KnowledgeFile, 81)).tenant_id = 202
        elif broken == "foreign_directory":
            session.add(KnowledgeFile(id=90, tenant_id=202, knowledge_id=40, file_name="foreign-dir", file_type=0))
        elif broken == "foreign_space":
            (await session.get(KnowledgeFile, 81)).knowledge_id = 999
        elif broken == "duplicate_file":
            session.add(KnowledgeDocumentVersion(id=190, document_id=80, knowledge_file_id=81, version_no=3))
        elif broken == "orphan_directory":
            session.add(KnowledgeFile(id=90, tenant_id=101, knowledge_id=40, file_name="folder", file_type=0))
            session.add(KnowledgeDocumentVersion(id=190, document_id=999, knowledge_file_id=90, version_no=1))
        elif broken == "primary":
            (await session.get(KnowledgeDocument, 80)).primary_version_id = 999
        elif broken == "multiple_primary":
            (await session.get(KnowledgeDocumentVersion, 182)).is_primary = True
        else:
            (await session.get(KnowledgeDocumentVersion, 181)).is_primary = False
        await session.commit()
    async with metadata.context.sessions() as session:
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await MetadataProcessingRepository().aload_scope(session, 40)


@pytest.mark.parametrize("status", [1, 4, 5])
async def test_inflight_physical_file_conflicts_without_filtering_it_out(metadata, status):
    async with metadata.context.sessions() as session:
        (await session.get(KnowledgeFile, 82)).status = status
        await session.commit()
    async with metadata.context.sessions() as session:
        with pytest.raises(KnowledgeProcessingConflictError):
            await MetadataProcessingRepository().aload_scope(session, 40)


@pytest.mark.parametrize("state,transition", [(2, None), (3, None), (1, {"operation_id": "pending"})])
async def test_space_processing_state_conflicts(metadata, state, transition):
    async with metadata.context.sessions() as session:
        root = await session.get(Knowledge, 40)
        root.state, root.model_transition = state, transition
        await session.commit()
    async with metadata.context.sessions() as session:
        with pytest.raises(KnowledgeProcessingConflictError):
            await MetadataProcessingRepository().aload_scope(session, 40)


@pytest.mark.parametrize("kind", ["metadata_schema_change", "file_reprocess", "embedding_rebuild"])
async def test_actual_active_task_conflicts_even_with_ready_projection(metadata, kind):
    async with metadata.context.sessions() as session:
        await metadata.owner.jobs.acreate(
            session,
            space_id=40,
            kind=kind,
            idempotency_key="active",
            actor_user_id=7,
            actor_reference={"actor_id": 7},
            parameters={},
            configuration=ProcessingConfiguration(0, "g0"),
            items=[NewProcessingItem(ResourceVersionTarget(file_id=81, document_id=80, version_id=181), 40)],
        )
        await session.commit()
    async with metadata.context.sessions() as session:
        with pytest.raises(KnowledgeProcessingConflictError):
            await MetadataProcessingRepository().aload_scope(session, 40)


async def test_401_versions_are_complete_and_queries_do_not_grow_per_version(metadata):
    async with metadata.context.sessions() as session:
        for number in range(399):
            session.add(
                KnowledgeFile(
                    id=1000 + number,
                    tenant_id=101,
                    knowledge_id=40,
                    file_name=str(number),
                    status=(2, 3, 6, 7)[number % 4],
                )
            )
            session.add(
                KnowledgeDocumentVersion(
                    id=2000 + number,
                    document_id=80,
                    knowledge_file_id=1000 + number,
                    version_no=number + 3,
                    is_primary=False,
                )
            )
        await session.commit()
    queries, primary_reads = [], 0
    original = KnowledgeDocumentVersion.__getattribute__

    def observe(instance, name):
        nonlocal primary_reads
        if name == "is_primary":
            primary_reads += 1
        return original(instance, name)

    def sql(connection, cursor, statement, parameters, context, many):
        queries.append(statement)

    event.listen(metadata.context.engine.sync_engine, "before_cursor_execute", sql)
    try:
        async with metadata.context.sessions() as session:
            with patch.object(KnowledgeDocumentVersion, "__getattribute__", observe):
                scope = await MetadataProcessingRepository().aload_scope(session, 40)
        assert len(scope.items) == 401 and {item.status for item in scope.items} == {2, 3, 6, 7}
        assert len(queries) <= 6 and primary_reads <= 401 * 3
    finally:
        event.remove(metadata.context.engine.sync_engine, "before_cursor_execute", sql)


async def test_strict_tenant_and_qa_rejection_do_not_use_visible_root_scope(metadata):
    async with metadata.context.sessions() as session:
        repo = MetadataProcessingRepository()
        for foreign in (20, 30, 12):
            with pytest.raises(SpaceNotFoundError):
                await repo.aload_scope(session, foreign)
        with bypass_tenant_filter(), pytest.raises(ResourceReferenceInvalidError):
            await repo.aload_scope(session, 40)
        with pytest.raises(TypeError):
            await repo.aload_scope(object(), 40)


async def test_schema_only_cas_uses_original_external_transaction(metadata):
    repo = MetadataProcessingRepository()
    async with metadata.context.sessions() as session:
        before_file = (await session.get(KnowledgeFile, 81)).model_dump(mode="json")
        scope = await repo.aload_scope(session, 40)
        changed = await repo.areplace_schema(
            session,
            scope,
            after_schema=(*scope.schema_fields, {"field_name": "new_field", "field_type": "number", "updated_at": 20}),
        )
        assert changed.schema_revision == 1 and len(changed.schema_fields) == 2
        assert (changed.model_config_revision, changed.index_generation) == (0, "g0")
        assert (await session.get(KnowledgeFile, 81)).model_dump(mode="json") == before_file
        await session.rollback()
    async with metadata.context.sessions() as session:
        assert (await repo.aload_scope(session, 40)).schema_revision == 0


@pytest.mark.parametrize("entry", ["repository", "service"])
@pytest.mark.parametrize(
    "dirty",
    [
        "revision",
        "schema_fields",
        "model_revision",
        "values",
        "source",
        "primary",
        "binding",
        "document",
        "new_file",
        "new_document",
        "new_version",
        "directory_version",
        "deleted_file",
    ],
)
async def test_schema_cas_refuses_key_pending_scope_changes_before_any_write(metadata, entry, dirty):
    from bisheng.knowledge.domain.services.metadata_processing_service import MetadataProcessingService

    repo, service = MetadataProcessingRepository(), MetadataProcessingService()
    if dirty == "directory_version":
        async with metadata.context.sessions() as session:
            session.add(KnowledgeFile(id=90, tenant_id=101, knowledge_id=40, file_name="folder", file_type=0))
            await session.commit()
    async with metadata.context.sessions() as session:
        scope = await repo.aload_scope(session, 40)
        from bisheng.knowledge.domain.schemas.processing_job import MetadataSchemaParameters

        plan = await service.apreview(
            session,
            40,
            MetadataSchemaParameters(
                expected_schema_revision=0,
                changes=[{"operation": "add", "field_name": "fresh", "field_type": "string"}],
            ),
        )
        if dirty in {"revision", "schema_fields", "model_revision"}:
            root = await session.get(Knowledge, 40)
            if dirty == "revision":
                root.metadata_schema_revision = 99
            elif dirty == "schema_fields":
                root.metadata_fields = []
            else:
                root.model_config_revision = 99
        elif dirty in {"values", "source", "deleted_file"}:
            row = await session.get(KnowledgeFile, 81)
            if dirty == "values":
                row.user_metadata = {"note": {"field_value": "changed-but-not-flushed"}}
            elif dirty == "source":
                row.object_name = "changed-but-not-flushed"
            else:
                await session.delete(row)
        elif dirty in {"primary", "binding"}:
            row = await session.get(KnowledgeDocumentVersion, 181)
            if dirty == "primary":
                row.is_primary = False
            else:
                row.knowledge_file_id = 82
        elif dirty == "document":
            (await session.get(KnowledgeDocument, 80)).primary_version_id = 182
        elif dirty == "new_file":
            session.add(KnowledgeFile(tenant_id=101, knowledge_id=40, file_name="unflushed", status=3))
        elif dirty == "new_document":
            session.add(KnowledgeDocument(knowledge_id=40))
        elif dirty == "new_version":
            session.add(KnowledgeDocumentVersion(document_id=80, knowledge_file_id=81, version_no=3))
        else:
            session.add(KnowledgeDocumentVersion(document_id=999, knowledge_file_id=90, version_no=1))
        with pytest.raises(KnowledgeOperationPlanConflictError):
            if entry == "repository":
                await repo.areplace_schema(session, scope, after_schema=())
            else:
                await service.aaccept(session, plan)
        with session.no_autoflush:
            revision = (await session.exec(select(Knowledge.metadata_schema_revision).where(Knowledge.id == 40))).one()
        assert revision == 0
        if dirty == "revision":
            assert root.metadata_schema_revision == 99
        await session.rollback()


async def test_unrelated_pending_writes_remain_owned_by_caller(metadata):
    repo = MetadataProcessingRepository()
    async with metadata.context.sessions() as session:
        scope = await repo.aload_scope(session, 40)
        root, other = await session.get(Knowledge, 40), await session.get(Knowledge, 10)
        root.name = "unrelated-name"
        other.metadata_schema_revision = 77
        changed = await repo.areplace_schema(session, scope, after_schema=scope.schema_fields)
        assert changed.schema_revision == 1 and root.name == "unrelated-name" and other.metadata_schema_revision == 77
        with session.no_autoflush:
            revision = (await session.exec(select(Knowledge.metadata_schema_revision).where(Knowledge.id == 40))).one()
        assert revision == 1
        await session.rollback()


async def test_other_root_file_document_version_and_model_pending_are_allowed(metadata):
    from bisheng.llm.domain.models.llm_server import LLMModel

    async with metadata.context.sessions() as session:
        session.add_all(
            [
                KnowledgeFile(id=191, tenant_id=101, knowledge_id=10, file_name="other", status=2),
                KnowledgeDocument(id=190, knowledge_id=10, primary_version_id=291),
                KnowledgeDocumentVersion(id=291, document_id=190, knowledge_file_id=191, version_no=1, is_primary=True),
            ]
        )
        await session.commit()
    async with metadata.context.sessions() as session:
        repo = MetadataProcessingRepository()
        scope = await repo.aload_scope(session, 40)
        row = await session.get(KnowledgeFile, 191)
        document = await session.get(KnowledgeDocument, 190)
        version = await session.get(KnowledgeDocumentVersion, 291)
        model = await session.get(LLMModel, 11)
        row.object_name, document.level, version.version_no, model.name = "other-object", 2, 2, "other-name"
        assert (await repo.areplace_schema(session, scope, after_schema=scope.schema_fields)).schema_revision == 1
        assert (row.object_name, document.level, version.version_no, model.name) == ("other-object", 2, 2, "other-name")
        await session.rollback()


def pending_job(*, space_id=40, state="accepted", key="pending-job"):
    return KnowledgeProcessingJob(
        tenant_id=101,
        space_id=space_id,
        kind="embedding_rebuild",
        state=state,
        actor_user_id=7,
        idempotency_key=key,
        request_hash="a" * 64,
        expected_model_config_revision=0,
    )


@pytest.mark.parametrize("entry", ["repository", "service"])
@pytest.mark.parametrize("change", ["new", "terminal_to_active", "move_into_scope", "expired_scope", "expired_state"])
async def test_pending_active_job_cannot_appear_during_schema_flush(metadata, entry, change):
    from bisheng.knowledge.domain.schemas.processing_job import MetadataSchemaParameters
    from bisheng.knowledge.domain.services.metadata_processing_service import MetadataProcessingService

    job_id = None
    if change != "new":
        async with metadata.context.sessions() as session:
            other = change in {"move_into_scope", "expired_state"}
            job = pending_job(space_id=10 if other else 40, state="running" if other else "failed")
            session.add(job)
            await session.commit()
            job_id = job.id
    async with metadata.context.sessions() as session:
        repo, service = MetadataProcessingRepository(), MetadataProcessingService()
        scope = await repo.aload_scope(session, 40)
        plan = await service.apreview(
            session,
            40,
            MetadataSchemaParameters(
                expected_schema_revision=0,
                changes=[{"operation": "add", "field_name": "fresh", "field_type": "string"}],
            ),
        )
        if change == "new":
            job = pending_job()
            session.add(job)
        else:
            job = await session.get(KnowledgeProcessingJob, job_id)
            if change == "expired_scope":
                session.expire(job, ["space_id"])
            elif change == "expired_state":
                session.expire(job, ["state"])
            if change in {"terminal_to_active", "expired_scope"}:
                job.state = "running"
            else:
                job.space_id = 40
        with pytest.raises(KnowledgeOperationPlanConflictError):
            if entry == "repository":
                await repo.areplace_schema(session, scope, after_schema=scope.schema_fields)
            else:
                await service.aaccept(session, plan)
        with session.no_autoflush:
            revision = (await session.exec(select(Knowledge.metadata_schema_revision).where(Knowledge.id == 40))).one()
        assert revision == 0
        await session.rollback()


async def test_unrelated_active_and_terminal_job_pending_remain_caller_owned(metadata):
    async with metadata.context.sessions() as session:
        terminal = pending_job(state="failed", key="terminal")
        session.add(terminal)
        await session.commit()
        terminal_id = terminal.id
    async with metadata.context.sessions() as session:
        repo = MetadataProcessingRepository()
        scope = await repo.aload_scope(session, 40)
        terminal = await session.get(KnowledgeProcessingJob, terminal_id)
        session.expire(terminal, ["space_id", "state"])
        terminal.error_message = "caller-owned audit"
        other = pending_job(space_id=10, key="other-active")
        session.add(other)
        assert (await repo.areplace_schema(session, scope, after_schema=scope.schema_fields)).schema_revision == 1
        assert terminal.error_message == "caller-owned audit" and other.state == "accepted"
        await session.rollback()


@pytest.mark.parametrize("drift", ["schema", "generation", "values", "source"])
async def test_cas_rechecks_real_scope_and_refuses_drift(metadata, drift):
    repo = MetadataProcessingRepository()
    async with metadata.context.sessions() as session:
        scope = await repo.aload_scope(session, 40)
        if drift in {"schema", "generation"}:
            values = {"metadata_schema_revision": 1} if drift == "schema" else {"index_generation": "new-generation"}
            await session.execute(
                update(Knowledge)
                .where(Knowledge.id == 40, Knowledge.tenant_id == 101)
                .values(**values)
                .execution_options(synchronize_session=False)
            )
        else:
            values = {"user_metadata": {"changed": True}} if drift == "values" else {"object_name": "replaced"}
            await session.execute(
                update(KnowledgeFile)
                .where(KnowledgeFile.id == 81, KnowledgeFile.tenant_id == 101)
                .values(**values)
                .execution_options(synchronize_session=False)
            )
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.areplace_schema(session, scope, after_schema=())
        await session.rollback()


async def test_empty_space_with_unattached_directories_has_real_empty_scope(metadata):
    async with metadata.context.sessions() as session:
        await session.execute(delete(KnowledgeDocumentVersion).where(KnowledgeDocumentVersion.document_id == 80))
        await session.execute(delete(KnowledgeDocument).where(KnowledgeDocument.knowledge_id == 40))
        await session.execute(
            delete(KnowledgeFile).where(KnowledgeFile.knowledge_id == 40, KnowledgeFile.tenant_id == 101)
        )
        session.add(KnowledgeFile(tenant_id=101, knowledge_id=40, file_name="folder", file_type=0))
        await session.commit()
    async with metadata.context.sessions() as session:
        repo = MetadataProcessingRepository()
        scope = await repo.aload_scope(session, 40)
        assert scope.items == ()
        result = await repo.areplace_schema(session, scope, after_schema=())
        assert result.schema_revision == 1
        assert not (await session.exec(select(KnowledgeDocumentVersion))).all()
