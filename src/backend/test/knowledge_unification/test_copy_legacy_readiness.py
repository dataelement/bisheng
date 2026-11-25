"""Historical copy tasks must not keep a logically ready space unusable."""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from bisheng.common.errcode.knowledge import KnowledgeProcessingConflictError
from bisheng.common.errcode.permission import PermissionDeniedError, PermissionPublishNotReadyError
from bisheng.knowledge.application.space_copy_owner import SpaceCopyOwner
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem as Item
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob as Job
from bisheng.permission.domain.models import PermissionProjectionOperation, ResourcePermissionMode
from test.knowledge_unification import test_kn_copy as fixtures

store, tenant, business, admission, processing, application, copying = (
    fixtures.store,
    fixtures.tenant,
    fixtures.business,
    fixtures.admission,
    fixtures.processing,
    fixtures.application,
    fixtures.copying,
)


async def historical_failure(copying, reason="copy_index_failed"):
    app, ctx = copying.app, copying.ctx
    accepted = await app.aconfirm(
        40,
        fixtures.command(await app.aprecheck(40, name="Historical failed copy", identity=ctx.user)),
        identity=ctx.user,
    )
    owner, sid, jid = SpaceCopyOwner(app), accepted["knowledge"].id, accepted["processing_job"].job_id
    lease = await owner.astart(jid, 0)
    while item := await owner.aclaim(lease):
        assert await owner.acomplete(item.lease, error_code=10996, failure_reason=reason)
    assert (await owner.afinalize(lease)).state == "failed"
    async with ctx.sessions() as session:
        root = await session.get(Knowledge, sid)
        # This is the state persisted by the pre-independent-copy implementation.
        root.state = 2
        session.add(root)
        await session.commit()
    return owner, sid, jid


async def durable_facts(copying, sid, jid):
    async with copying.ctx.sessions() as session:
        job = await session.get(Job, jid)
        items = (await session.execute(select(Item).where(Item.job_id == jid).order_by(Item.id))).scalars().all()
        files = (
            (
                await session.execute(
                    select(KnowledgeFile).where(KnowledgeFile.knowledge_id == sid).order_by(KnowledgeFile.id)
                )
            )
            .scalars()
            .all()
        )
        operations = (
            (await session.execute(select(PermissionProjectionOperation).order_by(PermissionProjectionOperation.id)))
            .scalars()
            .all()
        )
        return {
            "job": job.model_dump(mode="json"),
            "items": [x.model_dump(mode="json") for x in items],
            "files": [x.model_dump(mode="json") for x in files],
            "projections": [(x.id, x.status) for x in operations],
        }


@pytest.mark.parametrize("reason", ["copy_index_failed", "copy_input_failed"])
async def test_historical_failed_copy_becomes_usable_without_retrying_or_recopying_files(copying, reason):
    owner, sid, jid = await historical_failure(copying, reason)
    before = await durable_facts(copying, sid, jid)
    SpaceCopyOwner._initialize.reset_mock()
    await owner.aensure_logical(sid, jid, identity=copying.ctx.user, entry_kind="web")
    async with copying.ctx.sessions() as session:
        assert (await session.get(Knowledge, sid)).state == 1
    assert await durable_facts(copying, sid, jid) == before
    SpaceCopyOwner._initialize.assert_awaited_once()
    await owner.aensure_logical(sid, jid, identity=copying.ctx.user, entry_kind="web")
    SpaceCopyOwner._initialize.assert_awaited_once()
    assert await durable_facts(copying, sid, jid) == before


async def test_historical_readiness_is_not_published_when_index_initialization_fails(copying):
    owner, sid, jid = await historical_failure(copying)
    before = await durable_facts(copying, sid, jid)
    SpaceCopyOwner._initialize.side_effect = KnowledgeProcessingConflictError(reason="copy_vector_collection_not_ready")
    with pytest.raises(KnowledgeProcessingConflictError):
        await owner.aensure_logical(sid, jid, identity=copying.ctx.user, entry_kind="web")
    async with copying.ctx.sessions() as session:
        assert (await session.get(Knowledge, sid)).state == 2
    assert await durable_facts(copying, sid, jid) == before


async def test_historical_readiness_requires_original_permission_projection_receipts(copying, monkeypatch):
    owner, sid, jid = await historical_failure(copying)
    before = await durable_facts(copying, sid, jid)
    SpaceCopyOwner._initialize.reset_mock()
    monkeypatch.setattr(
        copying.bridge,
        "arequire_independent",
        AsyncMock(side_effect=KnowledgeProcessingConflictError(reason="copy_permission_not_ready")),
    )
    with pytest.raises(KnowledgeProcessingConflictError):
        await owner.aensure_logical(sid, jid, identity=copying.ctx.user, entry_kind="web")
    SpaceCopyOwner._initialize.assert_not_awaited()
    async with copying.ctx.sessions() as session:
        assert (await session.get(Knowledge, sid)).state == 2
    assert await durable_facts(copying, sid, jid) == before


@pytest.mark.parametrize("change", ["permission", "moved_file", "deleted_source"])
async def test_completed_copy_recovers_without_reading_or_authorizing_live_source(copying, monkeypatch, change):
    from sqlalchemy import delete

    owner, sid, jid = await historical_failure(copying)
    before = await durable_facts(copying, sid, jid)
    async with copying.ctx.sessions() as session:
        if change == "deleted_source":
            await session.execute(delete(ResourcePermissionMode).where(ResourcePermissionMode.resource_id == "40"))
            await session.execute(delete(Knowledge).where(Knowledge.id == 40))
        else:
            mode = (
                (
                    await session.execute(
                        select(ResourcePermissionMode).where(
                            ResourcePermissionMode.resource_id == ("40" if change == "permission" else "81")
                        )
                    )
                )
                .scalars()
                .one()
            )
            mode.version += 1
            if change == "moved_file":
                mode.parent_id = "999"
                mode.mode = "CUSTOM"
        await session.commit()
    source_check = AsyncMock(side_effect=AssertionError("live source must not gate a completed copy"))
    monkeypatch.setattr(owner.app, "authorize", source_check)
    await owner.aensure_logical(sid, jid, identity=copying.ctx.user, entry_kind="web")
    async with copying.ctx.sessions() as session:
        assert (await session.get(Knowledge, sid)).state == 1
    assert await durable_facts(copying, sid, jid) == before
    source_check.assert_not_awaited()


async def test_independent_copy_still_requires_current_target_permission(copying, monkeypatch):
    from bisheng.knowledge.application import space_copy_owner

    owner, sid, jid = await historical_failure(copying)
    before = await durable_facts(copying, sid, jid)
    monkeypatch.setattr(space_copy_owner, "require_business_action", AsyncMock(side_effect=PermissionDeniedError()))
    with pytest.raises(PermissionDeniedError):
        await owner.aensure_logical(sid, jid, identity=copying.ctx.user, entry_kind="web")
    async with copying.ctx.sessions() as session:
        assert (await session.get(Knowledge, sid)).state == 2
    assert await durable_facts(copying, sid, jid) == before


async def test_independent_copy_rejects_changed_target_permission_mirror(copying):
    owner, sid, jid = await historical_failure(copying)
    before = await durable_facts(copying, sid, jid)
    async with copying.ctx.sessions() as session:
        mode = (
            (
                await session.execute(
                    select(ResourcePermissionMode).where(
                        ResourcePermissionMode.resource_type == "knowledge_space",
                        ResourcePermissionMode.resource_id == str(sid),
                    )
                )
            )
            .scalars()
            .one()
        )
        mode.version += 1
        await session.commit()
    with pytest.raises(PermissionPublishNotReadyError):
        await owner.aensure_logical(sid, jid, identity=copying.ctx.user, entry_kind="web")
    async with copying.ctx.sessions() as session:
        assert (await session.get(Knowledge, sid)).state == 2
    assert await durable_facts(copying, sid, jid) == before


async def test_independent_copy_preserves_later_completed_target_grant_changes(copying):
    from dataclasses import replace

    from bisheng.permission.application.control_state import SqlGrantMutationState
    from bisheng.permission.application.identity import get_current_permission_actor
    from bisheng.permission.domain.services.grant_service import CanonicalGrantChange, GrantService

    owner, sid, jid = await historical_failure(copying)
    _, payload, mapping, _ = await owner._logical(sid, jid)
    actor = get_current_permission_actor()
    _, target, _, _ = owner._pairs(payload, mapping, sid, actor)[0]
    target = target.model_copy(update={"resource_version": 1})
    components = copying.bridge.composition.components
    facade = components.facade
    facade._grants = GrantService(
        source_service=facade._sources,
        projection=components.projection,
        state=SqlGrantMutationState(components.state),
    )
    source = facade._sources.canonicalize_source(
        source_id=1234567, subject_type="user", subject_id="99", source_type="DIRECT", source_ref="user:99"
    )
    changed = await facade.mutate_grants(
        actor=replace(actor, super_admin=True),
        target=target,
        changes=(CanonicalGrantChange(operation="ADD", model_key="owner", source=source),),
        expected_resource_version=1,
        expected_catalog_release_id=1,
        idempotency_key="later-target-change",
    )
    assert changed.resource_version == 2
    models = facade._models_for_target(await facade._runtime_catalog(), target.resource_type)
    before = await components.state.load_grants(target=target, models=models)
    await owner.aensure_logical(sid, jid, identity=copying.ctx.user, entry_kind="web")
    assert await components.state.load_grants(target=target, models=models) == before
    async with copying.ctx.sessions() as session:
        assert (await session.get(Knowledge, sid)).state == 1
