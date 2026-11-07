"""T926: native whole-history move scope; middleware transports stay unused."""

from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest
from sqlalchemy import event, update
from sqlmodel import Session
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, KnowledgeProcessingConflictError
from bisheng.common.errcode.knowledge_space import SpaceNotFoundError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import tenant_filter
from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.tag import Tag, TagLink
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan
from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
from bisheng.knowledge.domain.repositories.move_scope_repository import MoveRoot, MoveScopeRepository
from bisheng.permission.domain.models.grant import ResourcePermissionMode
from bisheng.permission.domain.repositories.move_projection_repository import MoveProjectionRepository
from test.knowledge_unification import test_kn_reference_repository as fixtures

store, tenant = fixtures.store, fixtures.tenant


@pytest.fixture
async def moving(store, monkeypatch):
    sync, engine = store
    models = (
        KnowledgeFile,
        KnowledgeDocument,
        KnowledgeDocumentVersion,
        KnowledgeOperationPlan,
        KnowledgeProcessingJob,
        KnowledgeProcessingItem,
        ResourcePermissionMode,
        Tag,
        TagLink,
    )
    for model in models:
        model.__table__.create(sync)
    names = tenant_filter._tenant_aware_tables | {
        model.__tablename__ for model in models if "tenant_id" in model.__table__.c
    }
    monkeypatch.setattr(tenant_filter, "_tenant_aware_tables", names)
    with Session(sync) as session, bypass_tenant_filter():
        source, target = session.get(Knowledge, 10), session.get(Knowledge, 11)
        source.metadata_fields = [
            {"field_name": "keep", "field_type": "string"},
            {"field_name": "lose", "field_type": "number"},
        ]
        target.metadata_fields = [
            {"field_name": "keep", "field_type": "string"},
            {"field_name": "lose", "field_type": "string"},
        ]
        source.index_name, source.collection_name = "source-es", "source-milvus"
        target.index_name, target.collection_name = "target-es", "target-milvus"
        session.add_all(
            [
                KnowledgeFile(
                    id=50, tenant_id=101, knowledge_id=10, file_type=0, file_name="folder", file_level_path="", level=0
                ),
                KnowledgeFile(
                    id=51, tenant_id=101, knowledge_id=11, file_type=0, file_name="target", file_level_path="", level=0
                ),
                KnowledgeFile(
                    id=81,
                    tenant_id=101,
                    knowledge_id=10,
                    file_name="visible.txt",
                    file_level_path="/50",
                    level=1,
                    status=2,
                    object_name="objects/81",
                    user_metadata={
                        "keep": {"field_value": "keep-private", "field_type": "string"},
                        "lose": {"field_value": 17, "field_type": "number"},
                    },
                ),
                KnowledgeFile(
                    id=82,
                    tenant_id=101,
                    knowledge_id=10,
                    file_name="history.html",
                    file_level_path="/50",
                    level=1,
                    status=7,
                    file_source="web_link",
                    object_name="objects/82",
                    user_metadata={
                        "source_url": "https://private.invalid",
                        "html_snapshot_object_name": "snap/82",
                        "keep": {"field_value": "history", "field_type": "string"},
                    },
                ),
                KnowledgeDocument(id=80, knowledge_id=10, primary_version_id=181, file_level_path="/50", level=1),
                KnowledgeDocumentVersion(id=181, document_id=80, knowledge_file_id=81, version_no=1, is_primary=True),
                KnowledgeDocumentVersion(id=182, document_id=80, knowledge_file_id=82, version_no=2),
                Tag(id=1, tenant_id=101, name="source-tag", business_type="knowledge_space", business_id="10"),
                TagLink(
                    id=1, tenant_id=101, tag_id=1, resource_id="81", resource_type=ResourceTypeEnum.SPACE_FILE.value
                ),
            ]
        )
        for kind, key, parent_kind, parent in (
            ("folder", 50, "knowledge_space", 10),
            ("folder", 51, "knowledge_space", 11),
            ("knowledge_file", 81, "folder", 50),
            ("knowledge_file", 82, "folder", 50),
        ):
            session.add(
                ResourcePermissionMode(
                    id=key,
                    tenant_id=101,
                    resource_type=kind,
                    resource_id=str(key),
                    mode="INHERIT",
                    parent_type=parent_kind,
                    parent_id=str(parent),
                    version=4,
                    projection_state="CURRENT",
                )
            )
        session.commit()
    return SimpleNamespace(
        sync=sync, engine=engine, repo=MoveScopeRepository(parent_states=MoveProjectionRepository(environment="test"))
    )


async def load(moving, session, roots=None, **kwargs):
    return await moving.repo.aload_scope(
        session,
        source_space_id=10,
        destination_space_id=11,
        roots=roots or (MoveRoot("folder", 50),),
        destination_folder_id=51,
        **kwargs,
    )


async def test_complete_history_and_confirmed_impact_without_writes(moving):
    async with AsyncSession(moving.engine) as session:
        scope = await load(moving, session, (MoveRoot("folder", 50), MoveRoot("file", 81)))
        assert scope.roots == (MoveRoot("folder", 50),)
        assert [row.file_id for row in scope.files] == [50, 81, 82]
        assert [
            (x.target.file_id, x.target.document_id, x.target.version_id, x.participates) for x in scope.leaves
        ] == [(81, 80, 181, True), (82, 80, 182, False)]
        assert scope.retained_fields == ("keep",) and scope.removed_fields == ("lose",)
        assert scope.tag_link_ids == (1,)
        assert [
            (x.resource_type, x.resource_id, x.new_parent_type, str(x.new_parent_id)) for x in scope.parent_changes
        ] == [("folder", 50, "folder", "51")]
        assert all(row.after["knowledge_id"] == 11 for row in scope.files)
        assert scope.files[1].after["file_level_path"] == "/51/50"
        assert scope.files[1].after["user_metadata"] == {
            "keep": {"field_value": "keep-private", "field_type": "string"}
        }
        assert scope.files[2].after["user_metadata"]["html_snapshot_object_name"] == "snap/82"
        assert scope.files[2].after["status"] == 7
        assert len(scope.scope_digest) == len(scope.changes_digest) == 64
        assert "keep-private" not in repr(scope) and "private.invalid" not in repr(scope)
        with pytest.raises(FrozenInstanceError):
            scope.source_space_id = 999
        assert not session.new and not session.dirty


async def test_single_selected_file_still_expands_all_versions(moving):
    async with AsyncSession(moving.engine) as session:
        scope = await load(moving, session, (MoveRoot("file", 81),))
        assert [row.file_id for row in scope.files] == [81, 82]
        assert len(scope.parent_changes) == 2
        assert all(x.destination_parent_id == 51 for x in scope.leaves)
        assert scope.documents[0].after["primary_version_id"] == 181


@pytest.mark.parametrize(
    "broken",
    [
        "missing-file",
        "foreign-file",
        "foreign-directory",
        "foreign-doc",
        "duplicate-file",
        "directory-version",
        "missing-doc",
        "missing-primary",
        "double-primary",
        "unversioned",
        "empty-doc",
    ],
)
async def test_bad_chains_cannot_vanish_through_inner_join(moving, broken):
    async with AsyncSession(moving.engine) as session:
        if broken == "missing-file":
            await session.delete(await session.get(KnowledgeFile, 82))
        elif broken == "foreign-file":
            (await session.get(KnowledgeFile, 82)).tenant_id = 202
        elif broken == "foreign-directory":
            (await session.get(KnowledgeFile, 50)).tenant_id = 202
        elif broken == "foreign-doc":
            (await session.get(KnowledgeDocument, 80)).knowledge_id = 20
        elif broken == "duplicate-file":
            session.add(KnowledgeDocumentVersion(id=183, document_id=80, knowledge_file_id=81, version_no=3))
        elif broken == "directory-version":
            session.add(KnowledgeDocumentVersion(id=183, document_id=999, knowledge_file_id=50, version_no=3))
        elif broken == "missing-doc":
            await session.delete(await session.get(KnowledgeDocument, 80))
        elif broken == "missing-primary":
            (await session.get(KnowledgeDocument, 80)).primary_version_id = 999
        elif broken == "double-primary":
            (await session.get(KnowledgeDocumentVersion, 182)).is_primary = True
        elif broken == "unversioned":
            session.add(
                KnowledgeFile(
                    id=83, tenant_id=101, knowledge_id=10, file_name="orphan", file_level_path="/50", level=1, status=3
                )
            )
        else:
            session.add(KnowledgeDocument(id=83, knowledge_id=10, file_level_path="/50", level=1))
        await session.commit()
    async with AsyncSession(moving.engine) as session:
        with pytest.raises((KnowledgeOperationPlanConflictError, SpaceNotFoundError)):
            await load(moving, session)


@pytest.mark.parametrize("status", [1, 4, 5])
async def test_inflight_is_conflict_not_silent_scope_shrink(moving, status):
    async with AsyncSession(moving.engine) as session:
        (await session.get(KnowledgeFile, 82)).status = status
        await session.commit()
    async with AsyncSession(moving.engine) as session:
        with pytest.raises(KnowledgeProcessingConflictError):
            await load(moving, session)
        assert (await session.get(KnowledgeFile, 82)).status == status


@pytest.mark.parametrize("bad", ["root", "parent", "version", "file", "new-version"])
async def test_critical_pending_is_rejected_without_autoflush_or_loss(moving, bad):
    async with AsyncSession(moving.engine, expire_on_commit=False) as session:
        if bad == "root":
            row = await session.get(Knowledge, 10)
            row.model_config_revision = 99
        elif bad == "parent":
            row = await session.get(KnowledgeFile, 51)
            row.knowledge_id = 999
        elif bad == "version":
            row = await session.get(KnowledgeDocumentVersion, 182)
            row.knowledge_file_id = 81
        elif bad == "new-version":
            row = KnowledgeDocumentVersion(document_id=80, knowledge_file_id=81, version_no=3)
            session.add(row)
        else:
            row = await session.get(KnowledgeFile, 81)
            row.user_metadata = {"changed": "pending"}
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await load(moving, session)
        assert row in session.dirty or row in session.new
        await session.rollback()


async def test_cached_root_and_unrelated_pending_are_preserved(moving):
    async with AsyncSession(moving.engine, expire_on_commit=False) as session:
        root, other = await session.get(Knowledge, 10), await session.get(Knowledge, 13)
        other.description = "caller-owned-pending"
        with session.no_autoflush:
            await session.execute(
                update(Knowledge)
                .where(Knowledge.id == 10, Knowledge.tenant_id == 101)
                .values(model_config_revision=8)
                .execution_options(synchronize_session=False)
            )
        scope = await load(moving, session)
        assert scope.source_model_config_revision == 8 and root.model_config_revision == 4
        assert other.description == "caller-owned-pending" and other in session.dirty


async def test_missing_port_is_fail_closed(moving):
    async with AsyncSession(moving.engine) as session:
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await MoveScopeRepository().aload_scope(
                session,
                source_space_id=10,
                destination_space_id=11,
                roots=(MoveRoot("file", 81),),
                destination_folder_id=None,
            )


@pytest.mark.parametrize("count", [401, 10001])
async def test_large_history_is_seek_paged_and_linear(moving, count):
    with Session(moving.sync) as session:
        for n in range(3, count + 1):
            session.add(
                KnowledgeFile(
                    id=1000 + n,
                    tenant_id=101,
                    knowledge_id=10,
                    file_name=str(n),
                    file_level_path="/50",
                    level=1,
                    status=3,
                )
            )
            session.add(
                KnowledgeDocumentVersion(id=20000 + n, document_id=80, knowledge_file_id=1000 + n, version_no=n)
            )
        session.commit()
    queries, writes = [], []

    def record(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            queries.append((statement, parameters))
        elif statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            writes.append(statement)

    event.listen(moving.engine.sync_engine, "before_cursor_execute", record)
    try:
        async with AsyncSession(moving.engine) as session:
            scope = await load(moving, session)
    finally:
        event.remove(moving.engine.sync_engine, "before_cursor_execute", record)
    assert len(scope.leaves) == count and len(scope.files) == count + 1
    assert not writes and len(queries) <= 16 + 8 * ((count + 199) // 200)
    assert all(len(parameters) <= 410 for _, parameters in queries)
    assert [x.target.version_id for x in scope.leaves] == sorted(x.target.version_id for x in scope.leaves)


@pytest.mark.parametrize("state", ["accepted", "running", "failed", "partial_failed", "obsolete"])
@pytest.mark.parametrize("sync", [False, True])
async def test_source_input_is_protected_until_item_succeeded_even_after_source_cleaned(moving, state, sync):
    from datetime import datetime, timedelta

    with Session(moving.sync) as session:
        session.add(
            KnowledgeOperationPlan(
                id="plan",
                tenant_id=101,
                actor_user_id=7,
                operation="move",
                space_id=10,
                operation_id="move-job",
                consumed_at=datetime.now(),
                request_hash="a" * 64,
                plan_digest="b" * 64,
                expires_at=datetime.now() + timedelta(hours=1),
            )
        )
        session.add(
            KnowledgeProcessingJob(
                id="move-job",
                tenant_id=101,
                space_id=11,
                kind="move_index",
                state=state,
                actor_user_id=7,
                idempotency_key="move",
                request_hash="c" * 64,
                expected_model_config_revision=4,
                total_count=1,
            )
        )
        session.add(
            KnowledgeProcessingItem(
                id="move-item",
                tenant_id=101,
                job_id="move-job",
                file_id=81,
                document_id=80,
                version_id=181,
                expected_space_id=11,
                state="failed",
                step="move_source_cleaned",
                checkpoint={"step": "move_source_cleaned"},
            )
        )
        session.commit()
    if sync:
        with Session(moving.sync) as session:
            with pytest.raises(KnowledgeProcessingConflictError):
                moving.repo.assert_no_unsettled_move_inputs(session, 10)
    else:
        async with AsyncSession(moving.engine) as session:
            with pytest.raises(KnowledgeProcessingConflictError):
                await moving.repo.aassert_no_unsettled_move_inputs(session, 10)
    with Session(moving.sync) as session:
        session.get(KnowledgeProcessingItem, "move-item").state = "succeeded"
        session.commit()
        moving.repo.assert_no_unsettled_move_inputs(session, 10)


async def test_pending_active_j1_cannot_be_flushed_after_scope_read(moving):
    async with AsyncSession(moving.engine) as session:
        job = KnowledgeProcessingJob(
            tenant_id=101,
            space_id=11,
            kind="embedding_rebuild",
            actor_user_id=7,
            idempotency_key="pending",
            request_hash="a" * 64,
            expected_model_config_revision=4,
        )
        session.add(job)
        with pytest.raises(KnowledgeProcessingConflictError):
            await load(moving, session)
        assert job in session.new


@pytest.mark.parametrize("sync", [False, True])
async def test_pending_item_can_not_break_a_released_input_inside_the_delete_transaction(moving, sync):
    from datetime import datetime, timedelta

    with Session(moving.sync) as session:
        session.add(
            KnowledgeOperationPlan(
                id="plan-pending",
                tenant_id=101,
                actor_user_id=7,
                operation="move",
                space_id=10,
                operation_id="done-job",
                consumed_at=datetime.now(),
                request_hash="a" * 64,
                plan_digest="b" * 64,
                expires_at=datetime.now() + timedelta(hours=1),
            )
        )
        session.add(
            KnowledgeProcessingJob(
                id="done-job",
                tenant_id=101,
                space_id=11,
                kind="move_index",
                state="succeeded",
                actor_user_id=7,
                idempotency_key="done",
                request_hash="c" * 64,
                expected_model_config_revision=4,
                total_count=1,
            )
        )
        session.add(
            KnowledgeProcessingItem(
                id="done-item",
                tenant_id=101,
                job_id="done-job",
                file_id=81,
                document_id=80,
                version_id=181,
                expected_space_id=11,
                state="succeeded",
            )
        )
        session.commit()
    if sync:
        with Session(moving.sync) as session:
            item = session.get(KnowledgeProcessingItem, "done-item")
            item.state = "failed"
            with pytest.raises(KnowledgeProcessingConflictError):
                moving.repo.assert_no_unsettled_move_inputs(session, 10)
            assert item in session.dirty
    else:
        async with AsyncSession(moving.engine) as session:
            item = await session.get(KnowledgeProcessingItem, "done-item")
            item.state = "failed"
            with pytest.raises(KnowledgeProcessingConflictError):
                await moving.repo.aassert_no_unsettled_move_inputs(session, 10)
            assert item in session.dirty


async def test_primary_physical_location_must_match_the_logical_document(moving):
    with Session(moving.sync) as session:
        session.add(
            KnowledgeFile(
                id=60, tenant_id=101, knowledge_id=10, file_type=0, file_name="outside", file_level_path="", level=0
            )
        )
        session.get(KnowledgeFile, 81).file_level_path = "/60"
        row = session.get(ResourcePermissionMode, 81)
        row.parent_id = "60"
        session.commit()
    async with AsyncSession(moving.engine) as session:
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await load(moving, session)


async def test_invalid_persisted_schema_returns_a_domain_conflict(moving):
    with Session(moving.sync) as session:
        session.get(Knowledge, 10).metadata_fields = {}
        session.commit()
    async with AsyncSession(moving.engine) as session:
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await load(moving, session)


@pytest.mark.parametrize(
    "key", ["source_type", "source_url", "final_url", "web_title", "imported_at", "html_snapshot_object_name"]
)
async def test_web_system_keys_survive_collision_while_ordinary_custom_values_are_removed(moving, key):
    with Session(moving.sync) as session:
        root = session.get(Knowledge, 10)
        root.metadata_fields = [*root.metadata_fields, {"field_name": key, "field_type": "string"}]
        ordinary = session.get(KnowledgeFile, 81)
        ordinary.user_metadata = {
            **ordinary.user_metadata,
            key: {"field_type": "string", "field_value": "ordinary-custom"},
        }
        web = session.get(KnowledgeFile, 82)
        web.user_metadata = {**web.user_metadata, key: "stable-web-system"}
        session.commit()
    async with AsyncSession(moving.engine) as session:
        scope = await load(moving, session)
        rows = {row.file_id: row for row in scope.files}
        assert key not in rows[81].after["user_metadata"]
        assert rows[82].after["user_metadata"][key] == "stable-web-system"


async def test_foreign_unversioned_descendant_directory_cannot_hide_behind_tenant_filter(moving):
    with Session(moving.sync) as session:
        session.add(
            KnowledgeFile(
                id=90,
                tenant_id=202,
                knowledge_id=10,
                file_name="foreign-dir",
                file_type=0,
                file_level_path="/50",
                level=1,
            )
        )
        session.commit()
    async with AsyncSession(moving.engine) as session:
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await load(moving, session)
