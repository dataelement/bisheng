"""§121: a collaborator cannot leave UOW work for an implicit SP/commit flush."""

import pytest

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from test.knowledge_unification import test_move_processing_owner as base

store, tenant, moving, accepted, application = base.store, base.tenant, base.moving, base.accepted, base.application


@pytest.mark.parametrize("pending", [None, "dirty", "new", "deleted"])
async def test_actual_ready_tail_uow_is_rejected_before_savepoint_release(application, monkeypatch, pending):
    app = application
    before = await base.refs.facts(app.built)
    original = app.owner.jobs.amark_move_ready

    async def late(session, **kwargs):
        result = await original(session, **kwargs)
        if pending == "dirty":
            (await session.get(base.File, 82)).knowledge_id = 10
        elif pending == "new":
            session.add(base.File(id=999, tenant_id=101, knowledge_id=11, file_name="late-unversioned", file_type=1))
        elif pending == "deleted":
            await session.delete(await session.get(base.File, 82))
        return result

    monkeypatch.setattr(app.owner.jobs, "amark_move_ready", late)
    if pending is None:
        assert await app.owner.aensure_logical(app.built.lease) is not None
        assert len(app.chat) == 1
        return
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await app.owner.aensure_logical(app.built.lease)
    assert await base.refs.facts(app.built) == before
    async with app.built.sessions() as session:
        assert await session.get(base.File, 999) is None
    assert not app.chat
