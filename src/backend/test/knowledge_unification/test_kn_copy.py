"""Copy native business + original F048 Owner/Grant journal; transport-only doubles."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.common.models.space_channel_member import SpaceChannelMember
from bisheng.database.models.tag import Tag, TagLink
from bisheng.knowledge.application import processing_identity
from bisheng.knowledge.application import space_copy as module
from bisheng.knowledge.application.space_copy_owner import SpaceCopyOwner
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem as Item
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob as Job
from bisheng.knowledge.domain.models.knowledge_space_tag_library import KnowledgeSpaceTagLibrary
from bisheng.knowledge.domain.schemas.processing_job import ProcessingCreateRequest
from bisheng.permission.application import control_state, sql_runtime
from bisheng.permission.application.control_state import (
    RuntimeCatalogSnapshot,
    RuntimeModelSnapshot,
    SqlOwnerProjectionState,
    SqlPermissionControlState,
)
from bisheng.permission.application.knowledge_copy_projection import KnowledgeCopyProjectionApplication
from bisheng.permission.application.runtime import F048PermissionRuntime, F048RuntimeComponents
from bisheng.permission.domain.models import (
    AuthorizationModelRelease,
    PermissionCatalogRelease,
    PermissionGrant,
    PermissionGrantAssignee,
    PermissionMigrationItem,
    PermissionMigrationRun,
    PermissionProjectionOperation,
    PermissionProjectionTuple,
    PermissionVisibleSourceProjection,
    ResourcePermissionMode,
)
from bisheng.permission.domain.repositories.move_projection_repository import MoveProjectionRepository
from bisheng.permission.domain.repositories.projection_repository import ProjectionRepository
from bisheng.permission.domain.services.grant_source_service import GrantModelSnapshot, GrantSourceService
from bisheng.permission.domain.services.owner_service import F048OwnerProjectionService
from bisheng.permission.domain.services.projection_service import ProjectionService
from test.knowledge_unification import test_job_service as native
from test.knowledge_unification.test_job_query_dispatch import actual_processing_task as actual_processing_task
from test.knowledge_unification.test_job_repo import job_tenant as job_tenant
from test.permission.test_f048_projection_service import FakeFGAProjection, FakeRecentMarker

store, tenant, business, admission, processing, application = (
    native.store,
    native.tenant,
    native.business,
    native.admission,
    native.processing,
    native.application,
)


@pytest.fixture
async def copying(application, monkeypatch):
    ctx = application.context
    metadata = sa.MetaData()
    models = (
        SpaceChannelMember,
        Tag,
        TagLink,
        KnowledgeSpaceTagLibrary,
        AuthorizationModelRelease,
        PermissionCatalogRelease,
        PermissionMigrationRun,
        PermissionMigrationItem,
        PermissionGrant,
        PermissionGrantAssignee,
        PermissionVisibleSourceProjection,
        ResourcePermissionMode,
        PermissionProjectionOperation,
        PermissionProjectionTuple,
    )
    for model in models:
        table = model.__table__.to_metadata(metadata)
        if "id" in table.c:
            table.c.id.type = sa.Integer()
    async with ctx.engine.begin() as connection:
        await connection.run_sync(lambda c: metadata.create_all(c, checkfirst=True))
        await connection.execute(
            sa.insert(AuthorizationModelRelease),
            {
                "id": 1,
                "environment": "test",
                "store_id": "store",
                "model_id": "model",
                "model_version": "f048",
                "model_checksum": "a" * 64,
                "required_relations_checksum": "b" * 64,
                "openfga_version": "1",
                "status": "ACTIVE",
            },
        )
        await connection.execute(
            sa.insert(PermissionCatalogRelease),
            {
                "id": 1,
                "release_key": "copy",
                "version": 1,
                "status": "CURRENT",
                "write_fenced": False,
                "required_authorization_model_release_id": 1,
                "draft_owner_id": 7,
                "idempotency_key": "catalog",
                "checksum": "c" * 64,
            },
        )
        await connection.execute(
            sa.insert(ResourcePermissionMode),
            [
                {
                    "id": i,
                    "tenant_id": 101,
                    "resource_type": kind,
                    "resource_id": str(ident),
                    "mode": "CUSTOM" if ident == 40 else "INHERIT",
                    "parent_type": None if ident == 40 else "knowledge_space",
                    "parent_id": None if ident == 40 else "40",
                    "version": 1,
                    "projection_state": "CURRENT",
                }
                for i, (kind, ident) in enumerate(
                    (("knowledge_space", 40), ("knowledge_file", 81), ("knowledge_file", 82)), 1
                )
            ],
        )
    for mod in (control_state, sql_runtime):
        monkeypatch.setattr(mod, "get_async_db_session", ctx.sessions)
    state = SqlPermissionControlState()
    actions = ("visible", "upload_file", "edit", "manage_permission", "move", "rename", "delete", "download", "use")
    catalog = RuntimeCatalogSnapshot(
        release_id=1,
        release_key="copy",
        version=1,
        checksum="c" * 64,
        store_id="store",
        model_id="model",
        model_checksum="a" * 64,
        models=(
            RuntimeModelSnapshot(
                GrantModelSnapshot("owner", True, actions, derived_level=4, allow_same_level=True),
                "Owner",
                "STANDARD",
                1,
            ),
        ),
        action_resource_scopes=tuple((code, ("knowledge_space", "knowledge_file", "folder")) for code in actions),
    )
    monkeypatch.setattr(state, "current_catalog", AsyncMock(return_value=catalog))
    transport, marker = FakeFGAProjection(set()), FakeRecentMarker()
    projections = ProjectionService(
        repository=ProjectionRepository(ctx.sessions),
        marker=marker,
        scope_guard=sql_runtime.SqlProjectionScopeGuard(),
        fga=transport,
        finalizer=sql_runtime.SqlProjectionFinalizer(),
    )
    sources = GrantSourceService()
    owner = F048OwnerProjectionService(
        source_service=sources, projection=projections, state=SqlOwnerProjectionState(state)
    )
    facade = F048PermissionRuntime(
        client=SimpleNamespace(store_id="store", model_id="model"),
        state=state,
        marker=marker,
        projection=projections,
        sources=sources,
        owner=owner,
        decision=None,
        grants=None,
        modes=None,
        explain=None,
    )
    components = F048RuntimeComponents(
        facade=facade, state=state, projection=projections, marker=marker, relations=None
    )
    bridge = KnowledgeCopyProjectionApplication(session_factory=ctx.sessions, components=components)
    bridge.composition.repository = MoveProjectionRepository(environment="test")
    ctx.user._runtime_credential_reference = {
        "kind": "web_session",
        "user_id": 7,
        "tenant_id": 101,
        "token_version": 0,
        "expires_at": (datetime.now() + timedelta(hours=1)).isoformat(),
    }
    monkeypatch.setattr(processing_identity, "resolve_web_runtime_identity", AsyncMock(return_value=ctx.user))
    from bisheng.permission.application.identity import PermissionActor

    monkeypatch.setattr(
        processing_identity,
        "resolve_permission_actor",
        AsyncMock(return_value=PermissionActor(user_id=7, tenant_id=101)),
    )
    monkeypatch.setattr(module, "require_business_action", AsyncMock())
    policy = SimpleNamespace(prepare=AsyncMock(return_value=object()), revalidate=AsyncMock())
    app = module.SpaceCopyApplication(
        session_factory=ctx.sessions, projection=bridge, creation_policy=policy, quota=AsyncMock()
    )
    monkeypatch.setattr(SpaceCopyOwner, "_initialize", AsyncMock())
    return SimpleNamespace(app=app, ctx=ctx, bridge=bridge, transport=transport)


def command(plan):
    return ProcessingCreateRequest(
        confirmation_id=plan.confirmation_id, plan_digest=plan.plan_digest, idempotency_key="copy-independent"
    )


async def test_real_copy_accepts_independent_history_model_and_original_permission_journal(copying):
    app, ctx = copying.app, copying.ctx
    plan = await app.aprecheck(40, name="Independent", identity=ctx.user)
    result = await app.aconfirm(40, command(plan), identity=ctx.user)
    root = result["knowledge"]
    assert root.id != 40 and root.state == 2 and root.model == "11" and not root.is_released
    assert result["processing_job"].accepted and not result["completed"]
    async with ctx.sessions() as session:
        source = await session.get(Knowledge, 40)
        job = await session.get(Job, result["processing_job"].job_id)
        items = (await session.execute(sa.select(Item).where(Item.job_id == job.id))).scalars().all()
        assert source.state == 1 and job.space_id == root.id and job.total_count == 2
        assert {row.processing_snapshot["source_file"]["id"] for row in items} == {81, 82}
        assert len({row.document_id for row in items}) == 1 and all(row.file_id not in {81, 82} for row in items)
        operations = (await session.execute(sa.select(PermissionProjectionOperation))).scalars().all()
        assert len(operations) == 3 and all(
            row.operation_type == "RESOURCE_COPY" and row.status == "FINALIZED" for row in operations
        )
    repeated = await app.aconfirm(40, command(plan), identity=ctx.user)
    assert repeated["knowledge"].id == root.id and repeated["processing_job"].reused


async def test_super_admin_is_not_a_copy_creator_shortcut(copying):
    async with copying.ctx.sessions() as session, session.begin():
        root = await session.get(Knowledge, 40)
        root.user_id = 999
    with pytest.raises(PermissionDeniedError):
        await copying.app.aprecheck(40, name="Denied", identity=copying.ctx.user)


async def test_actual_copy_lease_file_and_item_ack_preserve_source_and_finalize(copying):
    from bisheng.worker.knowledge.space_copy_worker import SpaceCopyResult

    app, ctx = copying.app, copying.ctx
    plan = await app.aprecheck(40, name="Native execution", identity=ctx.user)
    accepted = await app.aconfirm(40, command(plan), identity=ctx.user)
    owner = SpaceCopyOwner(app)
    job_id = accepted["processing_job"].job_id
    lease = await owner.astart(job_id, 0)
    assert lease is not None
    for _ in range(2):
        claimed = await owner.aclaim(lease)
        current = await owner.aguard(claimed.lease)
        assert current is not None
        result = SpaceCopyResult(
            claimed.item.file_id, 0, 0, 0, "a" * 64, current.snapshot["source_file"]["user_metadata"]
        )
        assert await owner.acomplete(claimed.lease, result=result)
    assert await owner.aclaim(lease) is None
    assert (await owner.afinalize(lease)).state == "succeeded"
    async with ctx.sessions() as session:
        source = await session.get(Knowledge, 40)
        assert source.state == 1 and source.model == "11"
        items = (await session.execute(sa.select(Item).where(Item.job_id == job_id))).scalars().all()
        assert all(row.state == "succeeded" and row.step == "copy_completed" for row in items)
        assert (await session.get(Knowledge, accepted["knowledge"].id)).state == 1


async def test_empty_copy_completes_real_r2_permission_and_has_no_async_source_lease(copying):
    from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
    from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
    from bisheng.knowledge.domain.repositories.source_move_input_repository import SourceMoveInputRepository

    async with copying.ctx.sessions() as session, session.begin():
        await session.execute(sa.delete(KnowledgeDocumentVersion).where(KnowledgeDocumentVersion.document_id == 80))
        await session.execute(sa.delete(KnowledgeDocument).where(KnowledgeDocument.knowledge_id == 40))
        await session.execute(
            sa.delete(KnowledgeFile).where(KnowledgeFile.tenant_id == 101, KnowledgeFile.knowledge_id == 40)
        )
    plan = await copying.app.aprecheck(40, name="Empty copy", identity=copying.ctx.user)
    result = await copying.app.aconfirm(40, command(plan), identity=copying.ctx.user)
    assert result["completed"] and result["processing_job"] is None and result["knowledge"].state == 1
    again = await copying.app.aconfirm(40, command(plan), identity=copying.ctx.user)
    assert again["completed"] and again["knowledge"].id == result["knowledge"].id
    async with copying.ctx.sessions() as session:
        assert (await session.execute(sa.select(sa.func.count()).select_from(Job))).scalar_one() == 0
        await SourceMoveInputRepository().arequire_released(session, space_id=40)


async def test_partial_copy_retries_only_failed_item_and_releases_source_after_native_final_ack(copying):
    from bisheng.common.errcode.knowledge import KnowledgeProcessingConflictError
    from bisheng.knowledge.domain.repositories.source_move_input_repository import SourceMoveInputRepository
    from bisheng.knowledge.domain.schemas.processing_job import ProcessingRetryRequest
    from bisheng.worker.knowledge.space_copy_worker import SpaceCopyResult

    app, ctx = copying.app, copying.ctx
    plan = await app.aprecheck(40, name="Retry copy", identity=ctx.user)
    accepted = await app.aconfirm(40, command(plan), identity=ctx.user)
    owner, jid = SpaceCopyOwner(app), accepted["processing_job"].job_id
    lease = await owner.astart(jid, 0)
    first = await owner.aclaim(lease)
    assert await owner.acomplete(first.lease, result=SpaceCopyResult(first.item.file_id, 0, 0, 0, "a" * 64, None))
    second = await owner.aclaim(lease)
    assert await owner.acomplete(second.lease, error_code=10998)
    failed = await owner.afinalize(lease)
    assert failed.state == "partial_failed"
    async with ctx.sessions() as session, session.begin():
        with pytest.raises(KnowledgeProcessingConflictError):
            await SourceMoveInputRepository().arequire_released(session, space_id=40)
    retry = await owner.aretry(
        jid,
        ProcessingRetryRequest(idempotency_key="retry-copy", expected_job_revision=failed.revision),
        identity=ctx.user,
    )
    assert retry.job_id == jid and retry.state == "accepted"
    retry_job, _ = await owner.aread(jid)
    next_lease = await owner.astart(jid, retry_job.revision)
    claimed = await owner.aclaim(next_lease)
    assert claimed.item.id == second.item.id
    assert await owner.acomplete(claimed.lease, result=SpaceCopyResult(claimed.item.file_id, 0, 0, 0, "b" * 64, None))
    assert await owner.aclaim(next_lease) is None
    assert (await owner.afinalize(next_lease)).state == "succeeded"
    async with ctx.sessions() as session:
        kept = await session.get(Item, first.item.id)
        assert kept.attempt == 1 and kept.result["target_payload_digest"] == "a" * 64
        await SourceMoveInputRepository().arequire_released(session, space_id=40)


async def test_copy_access_clips_actual_item_page_and_generic_read_cannot_bypass(copying, monkeypatch):
    from bisheng.common.errcode.knowledge import KnowledgeProcessingJobNotFoundError
    from bisheng.knowledge.application import move_processing_access, space_copy_access
    from bisheng.knowledge.application.space_copy_access import SpaceCopyAccess

    app, ctx = copying.app, copying.ctx
    plan = await app.aprecheck(40, name="Query copy", identity=ctx.user)
    result = await app.aconfirm(40, command(plan), identity=ctx.user)
    jid, sid = result["processing_job"].job_id, result["knowledge"].id
    async with ctx.sessions() as session:
        items = (
            (await session.execute(sa.select(Item).where(Item.job_id == jid).order_by(Item.file_id))).scalars().all()
        )
        visible_id = items[0].file_id
    monkeypatch.setattr(space_copy_access, "require_business_action", AsyncMock())

    async def actions(identity, *, resource_ids, **kwargs):
        return {str(ident): ("visible",) if ident == visible_id else () for ident in resource_ids}

    monkeypatch.setattr(move_processing_access, "batch_check_business_actions", actions)
    access = SpaceCopyAccess(SpaceCopyOwner(app))
    page = await access.alist_items(sid, jid, identity=ctx.user, page=1, page_size=1)
    assert page.total == 1 and [row.file_id for row in page.data] == [visible_id]
    assert (await access.aget(sid, jid, identity=ctx.user)).hidden_item_count == 1
    with pytest.raises(KnowledgeProcessingJobNotFoundError):
        await access.aget(40, jid, identity=ctx.user)
    from bisheng.knowledge.domain.services.processing_job_service import ProcessingJobService

    generic = ProcessingJobService(owner=SimpleNamespace(jobs=copying.app.jobs))
    generic._authorize = AsyncMock()
    async with ctx.sessions() as session:
        with pytest.raises(KnowledgeProcessingJobNotFoundError):
            await generic.aget(session, sid, jid, identity=ctx.user)


async def test_original_execute_task_runs_copy_branch_and_commits_native_ack(
    copying, actual_processing_task, monkeypatch
):
    from bisheng.knowledge.application.processing_owner import KnowledgeProcessingOwner
    from bisheng.worker.knowledge import processing_jobs, space_copy_jobs
    from bisheng.worker.knowledge.space_copy_worker import SpaceCopyResult

    app, ctx = copying.app, copying.ctx
    plan = await app.aprecheck(40, name="Worker copy", identity=ctx.user)
    result = await app.aconfirm(40, command(plan), identity=ctx.user)
    owner = SpaceCopyOwner(app)
    monkeypatch.setattr(processing_jobs, "get_async_db_session", ctx.sessions)
    monkeypatch.setattr(processing_jobs, "_new_owner", KnowledgeProcessingOwner)
    monkeypatch.setattr(space_copy_jobs, "SpaceCopyOwner", lambda: owner)

    async def write(*, snapshot, guard, **kwargs):
        await guard()
        return SpaceCopyResult(
            snapshot["target_file"]["id"], 0, 0, 0, "c" * 64, snapshot["source_file"]["user_metadata"]
        )

    monkeypatch.setattr(space_copy_jobs, "apply_space_copy_item", write)
    summary = await processing_jobs._execute_processing_job(result["processing_job"].job_id, 0)
    assert summary["state"] == "succeeded"
    async with ctx.sessions() as session:
        items = (await session.execute(sa.select(Item).where(Item.job_id == summary["job_id"]))).scalars().all()
        assert all(item.state == "succeeded" and item.step == "copy_completed" for item in items)
        assert (await session.get(Knowledge, 40)).state == 1


async def test_consumed_copy_keeps_original_actor_and_frozen_defaults_across_fresh_continuation(copying):
    app, ctx = copying.app, copying.ctx
    plan = await app.aprecheck(40, name="Frozen defaults", identity=ctx.user)
    first = await app.aconfirm(40, command(plan), identity=ctx.user)
    async with ctx.sessions() as session, session.begin():
        source = await session.get(Knowledge, 40)
        source.description = "A later description"
        source.processing_config_version += 1
    again = await app.aconfirm(40, command(plan), identity=ctx.user)
    assert again["knowledge"].id == first["knowledge"].id and again["processing_job"].reused
    async with ctx.sessions() as session:
        job = await session.get(Job, first["processing_job"].job_id)
        assert job.actor_reference["credential_reference"]["token_version"] == 0
        assert (await session.get(Knowledge, first["knowledge"].id)).description != "A later description"
