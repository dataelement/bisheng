"""Actual SPACE creation/removal preserves one SQL/R2 transaction and tombstones.

覆盖 AC: AC-68, AC-71, AC-79, AC-87, AC-88, AC-89, AC-91, AC-92.
SQLite, original business methods, deletion Plans and F048 journals are real.
Only authentication, Coverage status and FGA/index/storage transports are
isolated. Completion requires the original durable cleanup receipts.
"""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import sqlalchemy as sa
from sqlmodel import Session

from bisheng.channel.domain.models.channel_knowledge_sync import ChannelKnowledgeSync, ChannelKnowledgeSyncDao
from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.common.errcode.permission import PermissionProjectionFailedError
from bisheng.common.models.space_channel_member import (
    BusinessTypeEnum,
    MembershipStatusEnum,
    SpaceChannelMember,
    UserRoleEnum,
)
from bisheng.knowledge.application import knowledge_deletion, processing_identity
from bisheng.knowledge.application.model_reference import KnowledgeModelReferenceApplication as App
from bisheng.knowledge.application.reference_target_owner import KnowledgeReferenceTargetOwner
from bisheng.knowledge.domain import knowledge_rag
from bisheng.knowledge.domain.models import knowledge_file as file_module
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, QAKnowledge
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan
from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
from bisheng.knowledge.domain.models.knowledge_space_delete_job import KnowledgeSpaceDeleteJob
from bisheng.knowledge.domain.models.knowledge_space_tag_library import KnowledgeSpaceTagLibrary
from bisheng.knowledge.domain.repositories.model_reference_repository import KnowledgeModelReferenceRepository
from bisheng.knowledge.domain.services import knowledge_space_service as module
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.llm.domain.models.llm_server import LLMModel
from bisheng.permission.application import control_state, sql_runtime
from bisheng.permission.application.identity import PermissionActor
from bisheng.permission.application.runtime import F048PermissionRuntime
from bisheng.permission.domain.models import (
    AuthorizationModelRelease,
    PermissionCatalogRelease,
    PermissionGrant,
    PermissionGrantAssignee,
    PermissionProjectionOperation,
    PermissionProjectionTuple,
    PermissionVisibleSourceProjection,
    ResourcePermissionMode,
)
from bisheng.permission.domain.repositories.projection_repository import ProjectionRepository
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.projection_service import ProjectionService
from bisheng.permission.domain.services.resource_lifecycle_policy import TECHNICAL_MARKER_SUBJECTS
from bisheng.resource_reference.application import read_identity
from bisheng.resource_reference.application.target_verification import ReferenceTargetVerifier
from bisheng.resource_reference.application.write_runtime import ReferenceBindingRuntime
from bisheng.resource_reference.domain.repositories.coverage_repository import CoverageRepository
from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository
from test.knowledge_unification import test_kn_model_bindings as fixtures
from test.knowledge_unification.test_direct_delete_reference_query import SqlStatus
from test.knowledge_unification.test_model_share_projection_deferred import Marker, Transport

store = fixtures.store
tenant = fixtures.tenant
business = fixtures.business


@pytest.fixture
async def consumer(business, monkeypatch):
    for model in (SpaceChannelMember, KnowledgeFile, QAKnowledge, ChannelKnowledgeSync):
        model.__table__.create(business.sync)
    monkeypatch.setattr(module, "get_async_db_session", business.sessions)
    monkeypatch.setattr(KnowledgeService, "create_knowledge_base", Mock(side_effect=AssertionError("old library path")))
    for name in ("async_delete_knowledge", "aquery_by_id"):
        monkeypatch.setattr(module.KnowledgeDao, name, AsyncMock(side_effect=AssertionError("separate DAO Session")))
    monkeypatch.setattr(
        module.SpaceChannelMemberDao,
        "async_insert_member",
        AsyncMock(side_effect=AssertionError("separate creator commit")),
    )
    monkeypatch.setattr(
        module.LLMService,
        "get_workbench_llm",
        AsyncMock(return_value=SimpleNamespace(embedding_model=SimpleNamespace(id=11))),
    )
    monkeypatch.setattr(KnowledgeService, "_init_knowledge_indices_sync", Mock())
    monkeypatch.setattr(KnowledgeService, "delete_knowledge_file_in_vector", Mock())
    monkeypatch.setattr(KnowledgeService, "delete_knowledge_file_in_minio", Mock())
    for name in ("audit_create_knowledge_space", "audit_delete_knowledge_space"):
        monkeypatch.setattr(module.KnowledgeAuditTelemetryService, name, AsyncMock())
    monkeypatch.setattr(module.KnowledgeAuditTelemetryService, "telemetry_delete_knowledge", Mock())
    monkeypatch.setattr(module.KnowledgeSpaceTagLibraryDao, "adelete_private_for_knowledge", AsyncMock())
    monkeypatch.setattr(module.SpaceChannelMemberDao, "clean_space_member", AsyncMock())
    monkeypatch.setattr(module.SpaceChannelMemberDao, "async_get_members_by_space", AsyncMock(return_value=[]))
    adapter = SimpleNamespace(
        authorize_created=AsyncMock(),
        load_permission_record=AsyncMock(return_value=object()),
        project_delete=AsyncMock(),
    )
    service = KnowledgeSpaceService(request=None, login_user=business.user)
    service._resource_adapter = AsyncMock(return_value=adapter)
    service._permission_actor = AsyncMock(return_value=object())
    service._existing_creation = AsyncMock(return_value=None)
    service._assert_space_creation_quota = AsyncMock()
    service._is_auto_tag_feature_visible = AsyncMock(return_value=False)
    service._require_action = AsyncMock()
    service._list_space_child_resources = AsyncMock(return_value=[])
    service._load_resource_permission_records = AsyncMock(return_value=[])
    service._project_resource_deletes = AsyncMock()
    service._authorized_space_user_ids = AsyncMock(return_value=[])
    service._send_space_event_notification = AsyncMock()
    service._dispatch_knowledge_chat_rehome = Mock()
    return business, service, adapter


@pytest.fixture
async def deletion_consumer(consumer, monkeypatch):
    context, service, adapter = consumer
    models = (
        KnowledgeDocument,
        KnowledgeDocumentVersion,
        KnowledgeOperationPlan,
        KnowledgeProcessingJob,
        KnowledgeProcessingItem,
        KnowledgeSpaceDeleteJob,
        KnowledgeSpaceTagLibrary,
        AuthorizationModelRelease,
        PermissionCatalogRelease,
        ResourcePermissionMode,
        PermissionGrant,
        PermissionGrantAssignee,
        PermissionProjectionOperation,
        PermissionProjectionTuple,
        PermissionVisibleSourceProjection,
    )
    metadata = sa.MetaData()
    pending = [model.__table__ for model in models]
    while pending:
        original = pending.pop()
        if original.name in metadata.tables:
            continue
        table = original.to_metadata(metadata)
        if isinstance(table.c.id.type, sa.BigInteger):
            table.c.id.type = sa.Integer()
        pending.extend(foreign.column.table for foreign in original.foreign_keys)
    metadata.create_all(context.sync, checkfirst=True)
    from bisheng.core.database import tenant_filter

    names = tenant_filter._tenant_aware_tables | {
        table.name for table in metadata.tables.values() if "tenant_id" in table.c
    }
    monkeypatch.setattr(tenant_filter, "_tenant_aware_tables", names)
    monkeypatch.setattr(tenant_filter, "_discover_tenant_aware_tables", lambda: names)
    async with context.sessions() as session, session.begin():
        session.add(
            AuthorizationModelRelease(
                id=1,
                environment="test",
                store_id="store",
                model_version="v1",
                model_id="model",
                model_checksum="a" * 64,
                required_relations_checksum="b" * 64,
                openfga_version="1",
                status="ACTIVE",
            )
        )
        session.add(
            PermissionCatalogRelease(
                id=1,
                release_key="catalog",
                version=1,
                status="CURRENT",
                required_authorization_model_release_id=1,
                draft_owner_id=7,
                idempotency_key="catalog",
                checksum="c" * 64,
            )
        )

    async def pre_read(ident):
        async with context.sessions() as session:
            return (await session.execute(sa.select(Knowledge).where(Knowledge.id == ident))).scalar_one_or_none()

    # The entry point's original notification/audit read is outside the actual
    # deletion transaction. All mutation remains in the native deletion Owner.
    monkeypatch.setattr(module.KnowledgeDao, "aquery_by_id", AsyncMock(side_effect=pre_read))
    monkeypatch.setattr(file_module, "get_async_db_session", context.sessions)

    async def members(ident):
        async with context.sessions() as session:
            return (
                (
                    await session.execute(
                        sa.select(SpaceChannelMember).where(
                            SpaceChannelMember.business_type == BusinessTypeEnum.SPACE,
                            SpaceChannelMember.business_id == str(ident),
                        )
                    )
                )
                .scalars()
                .all()
            )

    monkeypatch.setattr(module.SpaceChannelMemberDao, "async_get_members_by_space", AsyncMock(side_effect=members))
    actor = PermissionActor(user_id=7, tenant_id=101)
    context.user._runtime_credential_reference = {
        "kind": "web_session",
        "user_id": 7,
        "tenant_id": 101,
        "token_version": context.user.token_version,
        "expires_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
    }
    monkeypatch.setattr(processing_identity, "resolve_web_runtime_identity", AsyncMock(return_value=context.user))
    monkeypatch.setattr(processing_identity, "resolve_permission_actor", AsyncMock(return_value=actor))
    monkeypatch.setattr(read_identity, "resolve_permission_actor", AsyncMock(return_value=actor))

    async def permitted(identity, *, resource_type, resource_ids, actions):
        return {str(ident): set(actions) for ident in resource_ids}

    from bisheng.knowledge.domain.services import knowledge_reference_service

    monkeypatch.setattr(knowledge_deletion, "require_business_action", AsyncMock())
    monkeypatch.setattr(knowledge_deletion, "batch_check_business_actions", permitted)
    monkeypatch.setattr(knowledge_deletion.admission, "batch_check_business_actions", permitted)
    monkeypatch.setattr(knowledge_reference_service, "require_business_action", AsyncMock())
    monkeypatch.setattr(knowledge_reference_service, "batch_check_business_actions", permitted)
    verifier = ReferenceTargetVerifier(
        {
            **context.runtime.verifier._owners,
            "knowledge_space": KnowledgeReferenceTargetOwner(),
            "knowledge_file": KnowledgeReferenceTargetOwner(),
        }
    )
    context.runtime = ReferenceBindingRuntime(ReferenceRepository(verifier=verifier), verifier)
    monkeypatch.setattr(fixtures.app_module, "get_reference_binding_runtime", AsyncMock(return_value=context.runtime))
    monkeypatch.setattr(fixtures.app_module, "get_reference_binding_runtime_sync", lambda: context.runtime)
    coverage = SimpleNamespace(events=[], failure=None, tail=None)

    def factory(session):
        port = SqlStatus(session, coverage)
        return CoverageRepository(port, global_port=port)

    pin = SimpleNamespace(
        release_id=1,
        release_key="catalog",
        checksum="c" * 64,
        store_id="store",
        model_id="model",
        model_checksum="a" * 64,
    )
    monkeypatch.setattr(sql_runtime, "get_async_db_session", context.sessions)
    monkeypatch.setattr(control_state, "get_async_db_session", context.sessions)
    control = control_state.SqlPermissionControlState()
    monkeypatch.setattr(control, "current_catalog", AsyncMock(return_value=pin))
    context.order, context.projected_snapshots = [], []

    class ProjectionTransport(Transport):
        fail = False

        async def write_atomic(self, *, writes, deletes):
            context.projected_snapshots.append(state(context))
            if self.fail:
                raise RuntimeError("projection failed")
            context.order.extend(("fga", delta.object) for delta in deletes)
            return await super().write_atomic(writes=writes, deletes=deletes)

    transport = ProjectionTransport()
    transport.present.update(
        (subject, "permission_enabled", target)
        for subject in TECHNICAL_MARKER_SUBJECTS
        for target in ("folder:501", "knowledge_file:503", "knowledge_space:40")
    )
    projections = ProjectionService(
        repository=ProjectionRepository(context.sessions),
        marker=Marker(),
        scope_guard=sql_runtime.SqlProjectionScopeGuard(),
        fga=transport,
        finalizer=sql_runtime.SqlProjectionFinalizer(),
    )
    runtime = F048PermissionRuntime(
        client=SimpleNamespace(store_id="store", model_id="model"),
        state=control,
        marker=Marker(),
        decision=None,
        projection=projections,
        sources=None,
        owner=None,
        grants=None,
        modes=None,
        explain=None,
    )
    monkeypatch.setattr(knowledge_deletion, "get_f048_runtime", AsyncMock(return_value=runtime))

    async def load_record(*, resource_type, resource_id):
        async with context.sessions() as session:
            mode = (
                await session.execute(
                    sa.select(ResourcePermissionMode).where(
                        ResourcePermissionMode.resource_type == resource_type,
                        ResourcePermissionMode.resource_id == resource_id,
                    )
                )
            ).scalar_one()
            return SimpleNamespace(
                tenant_id=mode.tenant_id,
                resource_type=resource_type,
                resource_id=resource_id,
                resource_version=mode.version,
                parent_type=mode.parent_type,
                parent_id=mode.parent_id,
            )

    def lifecycle(record, *_args):
        return VerifiedPermissionTarget.from_business_service(**vars(record), context_version="native-space-lifecycle")

    native_adapter = SimpleNamespace(load_permission_record=load_record, _lifecycle_target=lifecycle)
    monkeypatch.setattr(knowledge_deletion, "get_f048_resource_adapter", AsyncMock(return_value=native_adapter))
    app = knowledge_deletion.KnowledgeDeletionApplication(
        session_factory=context.sessions,
        coverage_factory=factory,
        runtime=context.runtime,
    )
    context.deletion, context.transport = app, transport
    service.deletion_application_factory = lambda: app
    wire_cleanup_transports(context, monkeypatch)
    return context, service, adapter


def wire_cleanup_transports(context, monkeypatch):
    """Run the actual leased purge steps and native identity checks, isolating only IO."""
    from pymilvus import utility

    from bisheng.core.storage.minio import minio_manager
    from bisheng.knowledge.domain.services.knowledge_space_direct_delete_service import (
        KnowledgeSpaceDirectDeleteService,
    )

    @contextmanager
    def sync_sessions():
        with Session(context.sync) as session:
            yield session

    monkeypatch.setattr(knowledge_rag, "get_sync_db_session", sync_sessions)
    objects = {"original/503.txt", "preview/503.txt"}
    vectors = SimpleNamespace(es_exists=True, es_ids={503}, milvus_exists=True, milvus_ids={503})

    async def remove_object(*, bucket_name, object_name):
        objects.discard(object_name)

    storage = SimpleNamespace(
        bucket="bisheng",
        remove_object=remove_object,
        object_exists=AsyncMock(side_effect=lambda **kw: kw["object_name"] in objects),
    )
    monkeypatch.setattr(minio_manager, "get_minio_storage", AsyncMock(return_value=storage))

    class Indices:
        def exists(self, **kwargs):
            return vectors.es_exists

        def delete(self, **kwargs):
            vectors.es_exists = False

        def refresh(self, **kwargs):
            return None

    class Client:
        indices = Indices()

        def delete_by_query(self, **kwargs):
            vectors.es_ids.clear()
            return {"failures": []}

        def count(self, **kwargs):
            return {"count": len(vectors.es_ids)}

    class Collection:
        def drop(self):
            vectors.milvus_exists = False

        def delete(self, **kwargs):
            vectors.milvus_ids.clear()

        def flush(self):
            return None

        def query(self, **kwargs):
            return [{"count(*)": len(vectors.milvus_ids)}]

    monkeypatch.setattr(
        knowledge_rag.ElasticsearchFactory, "init_vectorstore_sync", Mock(return_value=SimpleNamespace(client=Client()))
    )
    monkeypatch.setattr(
        knowledge_rag.MilvusFactory,
        "init_vectorstore",
        Mock(return_value=SimpleNamespace(col=Collection(), alias="test")),
    )
    monkeypatch.setattr(utility, "has_collection", Mock(side_effect=lambda *args, **kw: vectors.milvus_exists))
    monkeypatch.setattr(
        knowledge_rag.LLMService,
        "get_bisheng_knowledge_embedding_sync",
        Mock(side_effect=AssertionError("cleanup must not execute a model")),
    )
    native = KnowledgeSpaceDirectDeleteService(session_factory=context.sessions)

    async def purge(step, job):
        with context.sync.connect() as connection:
            stored = (
                connection.execute(
                    sa.select(KnowledgeSpaceDeleteJob.__table__).where(KnowledgeSpaceDeleteJob.id == job.id)
                )
                .mappings()
                .one()
            )
            assert stored["business_phase"] == "finalized" and stored["state"] == "RUNNING"
            assert "fga" in stored["completed_steps"]
            assert not connection.execute(
                sa.select(KnowledgeFile.id).where(KnowledgeFile.id.in_(job.manifest["rows"]))
            ).first()
        context.order.append(("purge", step))
        await native._purge_step(step, job)

    context.deletion.purge_step = purge
    context.objects, context.vectors = objects, vectors


def state(context):
    result = fixtures.state(context)
    with context.sync.connect() as connection:
        for model in (SpaceChannelMember, KnowledgeFile, QAKnowledge, ChannelKnowledgeSync):
            result[model.__tablename__] = (
                connection.execute(sa.select(model.__table__).order_by(model.id)).mappings().all()
            )
        if hasattr(context, "deletion"):
            for model in (KnowledgeDocument, KnowledgeDocumentVersion):
                result[model.__tablename__] = (
                    connection.execute(sa.select(model.__table__).order_by(model.id)).mappings().all()
                )
    return result


async def seed(context):
    async with context.sessions() as session:
        row = Knowledge(
            id=40,
            tenant_id=101,
            user_id=7,
            name="space",
            type=3,
            model="11",
            index_name="index40",
            collection_name="col40",
        )
        await App.acreate(session, row, login_user=context.user, project_created=AsyncMock())
        session.add_all(
            [
                KnowledgeFile(
                    id=501, tenant_id=101, knowledge_id=40, file_name="folder", file_type=0, status=2, level=0
                ),
                KnowledgeFile(id=502, tenant_id=202, knowledge_id=20, file_name="foreign", status=2),
                KnowledgeFile(
                    id=503,
                    tenant_id=101,
                    knowledge_id=40,
                    file_name="doc.txt",
                    file_type=1,
                    status=2,
                    level=1,
                    file_level_path="/501",
                    object_name="original/503.txt",
                    preview_file_object_name="preview/503.txt",
                ),
                KnowledgeDocument(id=601, knowledge_id=40, file_level_path="/501", level=1, primary_version_id=701),
                KnowledgeDocumentVersion(id=701, document_id=601, knowledge_file_id=503, version_no=1, is_primary=True),
                # QA belongs to the existing independent type=1 root 12.
                QAKnowledge(id=501, tenant_id=101, knowledge_id=12, questions=["q"], answers="a"),
                ChannelKnowledgeSync(channel_id="channel", knowledge_space_id="40", folder_id="501", user_id=7),
                ResourcePermissionMode(
                    id=1,
                    tenant_id=101,
                    resource_type="folder",
                    resource_id="501",
                    mode="INHERIT",
                    parent_type="knowledge_space",
                    parent_id="40",
                    version=1,
                    projection_state="CURRENT",
                ),
                ResourcePermissionMode(
                    id=2,
                    tenant_id=101,
                    resource_type="knowledge_file",
                    resource_id="503",
                    mode="INHERIT",
                    parent_type="folder",
                    parent_id="501",
                    version=1,
                    projection_state="CURRENT",
                ),
                ResourcePermissionMode(
                    id=3,
                    tenant_id=101,
                    resource_type="knowledge_space",
                    resource_id="40",
                    mode="CUSTOM",
                    version=1,
                    projection_state="CURRENT",
                ),
            ]
        )
        await session.commit()


async def test_actual_space_creation_commits_space_creator_and_reference_before_indices(consumer):
    context, service, adapter = consumer
    context.user.tenant_id = 1  # home identity must not replace selected tenant101

    def index_after_commit(user_id, actual):
        facts = state(context)
        assert any(row["id"] == actual.id and row["tenant_id"] == 101 for row in facts["knowledge"])
        assert any(row["source_id"] == str(actual.id) for row in facts["business_resource_reference"])
        member = next(row for row in facts["space_channel_member"] if row["business_id"] == str(actual.id))
        assert member["business_type"] == BusinessTypeEnum.SPACE and member["user_id"] == 7
        assert member["user_role"] == UserRoleEnum.CREATOR and member["status"] == MembershipStatusEnum.ACTIVE
        assert user_id == 7

    KnowledgeService._init_knowledge_indices_sync.side_effect = index_after_commit
    result = await service.create_knowledge_space(name="new space")
    assert result.tenant_id == 101 and result.user_id == 7 and context.user.tenant_id == 1
    adapter.authorize_created.assert_awaited_once()
    record = adapter.authorize_created.call_args.kwargs["record"]
    assert record.resource_type == "knowledge_space" and record.resource_id == str(result.id)
    assert record.tenant_id == 101
    KnowledgeService._init_knowledge_indices_sync.assert_called_once()


@pytest.mark.parametrize("failure", ["projection", "membership", "bindings"])
async def test_space_create_failure_rolls_back_actual_resource_creator_and_bindings(consumer, monkeypatch, failure):
    context, service, adapter = consumer
    before = state(context)
    if failure == "projection":
        adapter.authorize_created.side_effect = RuntimeError("projection failed")
    elif failure == "membership":
        monkeypatch.setattr(
            KnowledgeModelReferenceRepository,
            "aadd_space_creator",
            AsyncMock(side_effect=RuntimeError("membership failed")),
            raising=False,
        )
    else:
        monkeypatch.setattr(
            context.runtime, "aapply_source_bindings", AsyncMock(side_effect=RuntimeError("bindings failed"))
        )
    with pytest.raises(RuntimeError, match=f"{failure} failed"):
        await service.create_knowledge_space(name="cancelled")
    assert state(context) == before
    KnowledgeService._init_knowledge_indices_sync.assert_not_called()


@pytest.mark.parametrize("clear", [False, True])
async def test_space_delete_clear_keep_projection_order_atomic_refs_and_sync_original_ids(deletion_consumer, clear):
    context, service, _ = deletion_consumer
    await seed(context)
    before = state(context)
    await (service.clear_space(40) if clear else service.delete_space(40))
    after = state(context)
    assert context.projected_snapshots and all(snapshot == before for snapshot in context.projected_snapshots)
    expected = {"folder:501", "knowledge_file:503"} | (set() if clear else {"knowledge_space:40"})
    assert {value for phase, value in context.order if phase == "fga"} == expected
    assert context.order[-3:] == [("purge", "minio"), ("purge", "es"), ("purge", "milvus")]
    assert_completed(context, expected)
    assert after["channel_knowledge_sync"] == before["channel_knowledge_sync"]
    assert [row["tenant_id"] for row in after["knowledgefile"]] == [202]
    assert after["qaknowledge"] == before["qaknowledge"]
    assert after["qaknowledge"][0]["knowledge_id"] == 12
    assert next(row for row in after["knowledge"] if row["id"] == 12)["type"] == 1
    assert next(row for row in after["knowledge"] if row["id"] == 12) == next(
        row for row in before["knowledge"] if row["id"] == 12
    )
    assert not after["knowledge_document"] and not after["knowledge_document_version"]
    if clear:
        assert after["business_resource_reference"] == before["business_resource_reference"]
        assert after["business_reference_set"] == before["business_reference_set"]
        assert any(row["id"] == 40 and row["model"] == "11" for row in after["knowledge"])
    else:
        assert all(row["id"] != 40 for row in after["knowledge"])
        assert not after["business_resource_reference"]
        source = next(
            row
            for row in after["business_reference_set"]
            if row["source_id"] == "40" and row["record_kind"] == "source"
        )
        assert not source["effective"] and source["ready"]


async def test_space_projection_failure_keeps_business_refs_and_does_not_purge(deletion_consumer):
    context, service, _ = deletion_consumer
    await seed(context)
    before = state(context)
    context.transport.fail = True
    with pytest.raises(
        PermissionProjectionFailedError, match="projection retry outcome is not full after state"
    ) as failure:
        await service.delete_space(40)
    assert isinstance(failure.value.__context__, RuntimeError)
    assert str(failure.value.__context__) == "projection failed"
    assert state(context) == before
    KnowledgeService.delete_knowledge_file_in_vector.assert_not_called()
    assert not context.order
    assert context.objects == {"original/503.txt", "preview/503.txt"}
    assert context.vectors.es_ids == context.vectors.milvus_ids == {503}
    with context.sync.connect() as connection:
        job = connection.execute(sa.select(KnowledgeSpaceDeleteJob.__table__)).mappings().one()
        assert job["business_phase"] == "prepared" and job["completed_steps"] == []
        assert job["state"] == "PENDING"
        journal = connection.execute(sa.select(PermissionProjectionOperation.__table__)).mappings().one()
        assert journal["status"] == "FAILED_CLOSED"


async def test_clear_does_not_require_deleted_model_execution_or_release_model_binding(deletion_consumer):
    context, service, _ = deletion_consumer
    await seed(context)
    async with context.sessions() as session, session.begin():
        await session.execute(sa.delete(LLMModel).where(LLMModel.id == 11, LLMModel.tenant_id == 101))
    before = state(context)
    await service.clear_space(40)
    assert state(context)["business_resource_reference"] == before["business_resource_reference"]
    assert_completed(context, {"folder:501", "knowledge_file:503"})
    knowledge_rag.LLMService.get_bisheng_knowledge_embedding_sync.assert_not_called()


@pytest.mark.parametrize("batch", [False, True])
async def test_folder_delete_does_not_silently_unbind_retained_channel_configuration(
    deletion_consumer, monkeypatch, batch
):
    context, service, _ = deletion_consumer
    await seed(context)
    service._ensure_space_async_task_tenant_consistency = Mock()
    service.update_folder_update_time = AsyncMock()
    service._require_read_permission = AsyncMock()
    monkeypatch.setattr(module.KnowledgeDao, "async_update_knowledge_update_time_by_id", AsyncMock())
    cleanup = AsyncMock(side_effect=AssertionError("retained config must not be deleted"))
    monkeypatch.setattr(ChannelKnowledgeSyncDao, "adelete_by_folder_ids", cleanup)
    before = state(context)["channel_knowledge_sync"]
    await (service.batch_delete(40, [], [501]) if batch else service.delete_folder(40, 501))
    cleanup.assert_not_called()
    assert state(context)["channel_knowledge_sync"] == before
    assert_completed(context, {"folder:501", "knowledge_file:503"})


def assert_completed(context, expected):
    with context.sync.connect() as connection:
        job = connection.execute(sa.select(KnowledgeSpaceDeleteJob.__table__)).mappings().one()
        assert job["state"] == "SUCCEEDED" and job["business_phase"] == "finalized"
        assert job["completed_steps"] == ["fga", "minio", "es", "milvus"]
        assert job["tenant_id"] == 101 and job["space_id"] == 40
        assert job["manifest"]["file_ids"] == [503] and job["manifest"]["folder_ids"] == [501]
        assert job["manifest"]["version_ids"] == [701] and job["manifest"]["document_ids"] == [601]
        journals = connection.execute(sa.select(PermissionProjectionOperation.__table__)).mappings().all()
        assert len(journals) == len(expected)
        assert all(
            row["status"] == "FINALIZED"
            and row["operation_type"] == "RESOURCE_DELETE"
            and row["commit_checksum"] == "f" * 64
            for row in journals
        )
    assert not context.objects
    assert not context.vectors.es_exists or not context.vectors.es_ids
    assert not context.vectors.milvus_exists or not context.vectors.milvus_ids
    assert all(
        call.args[0] == "index40" for call in knowledge_rag.ElasticsearchFactory.init_vectorstore_sync.call_args_list
    )
    assert all(call.args[0] == "col40" for call in knowledge_rag.MilvusFactory.init_vectorstore.call_args_list)
    knowledge_rag.LLMService.get_bisheng_knowledge_embedding_sync.assert_not_called()


async def test_foreign_file_attached_to_local_space_blocks_before_plan_projection_and_cleanup(deletion_consumer):
    context, service, _ = deletion_consumer
    await seed(context)
    async with context.sessions() as session, session.begin():
        await session.execute(
            sa.update(KnowledgeFile)
            .where(KnowledgeFile.id == 502, KnowledgeFile.tenant_id == 202)
            .values(knowledge_id=40)
        )
    before = state(context)
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await service.delete_space(40)
    assert state(context) == before
    assert not context.order and not context.projected_snapshots
    with context.sync.connect() as connection:
        assert not connection.execute(sa.select(KnowledgeOperationPlan.id)).first()
        assert not connection.execute(sa.select(KnowledgeSpaceDeleteJob.id)).first()
        assert not connection.execute(sa.select(PermissionProjectionOperation.id)).first()
