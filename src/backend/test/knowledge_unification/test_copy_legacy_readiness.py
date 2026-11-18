"""Historical copy tasks must not keep a logically ready space unusable."""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from bisheng.common.errcode.knowledge import KnowledgeProcessingConflictError
from bisheng.knowledge.application.space_copy_owner import SpaceCopyOwner
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem as Item
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob as Job
from bisheng.permission.domain.models import PermissionProjectionOperation
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
        "arequire_completed",
        AsyncMock(side_effect=KnowledgeProcessingConflictError(reason="copy_permission_not_ready")),
    )
    with pytest.raises(KnowledgeProcessingConflictError):
        await owner.aensure_logical(sid, jid, identity=copying.ctx.user, entry_kind="web")
    SpaceCopyOwner._initialize.assert_not_awaited()
    async with copying.ctx.sessions() as session:
        assert (await session.get(Knowledge, sid)).state == 2
    assert await durable_facts(copying, sid, jid) == before
