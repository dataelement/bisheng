"""Actual M2 and M3 paths refuse incomplete, hash-consistent Member graphs.

覆盖 AC: AC-55, AC-57, AC-80, AC-83, AC-85.
"""

from contextlib import asynccontextmanager

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.knowledge.application.unification_conversion import UnificationSQLConversionApplication
from test.knowledge_unification import test_migration_inventory_application as original

resource_native = original.resource_native
native = original.native
module = original.module
complete = original.complete
transport = original.transport


@pytest.mark.parametrize("missing", ["space_membership_header", "creator", "resource_conversion"])
async def test_actual_fresh_inventory_cannot_freeze_an_incomplete_producer(module, complete, transport, missing):
    app = original.application(module, transport)
    actual = app.preflight.aiter_tenant

    async def incomplete(*args, **kwargs):
        async for section, record in actual(*args, **kwargs):
            if getattr(record, "record_type", None) != missing:
                yield section, record

    app.preflight.aiter_tenant = incomplete
    async with AsyncSession(complete.engine) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError) as failure:
            await app.arun(session, **transport.inputs)
    assert "membership_inventory_" in failure.value.kwargs["reason"]
    assert await original.count_runs(complete.engine) == 0


@pytest.mark.parametrize("missing", ["space_membership_header", "resource_conversion"])
async def test_actual_frozen_replay_and_m3_admission_reject_incomplete_graph_before_writes(
    module, complete, transport, monkeypatch, missing
):
    actual_add = module._Pages.add

    async def old_artifact(pages, section, tenant_id, record, *, kind="baseline"):
        # Produce a closed, correctly hashed old graph with a missing section.
        # The current producer still supplies real complete facts to fresh checks.
        if getattr(record, "record_type", None) != missing:
            await actual_add(pages, section, tenant_id, record, kind=kind)

    with monkeypatch.context() as patch:
        patch.setattr(module._Pages, "add", old_artifact)
        async with AsyncSession(complete.engine) as session, session.begin():
            frozen = await original.application(module, transport).arun(session, **transport.inputs)
    assert frozen.baseline_ref["sha256"] and frozen.plan_ref["sha256"]
    complete.queries.clear()
    async with AsyncSession(complete.engine) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError) as replay:
            await original.application(module, transport).arun(session, **transport.inputs)
    assert "membership_inventory_" in replay.value.kwargs["reason"]

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(complete.engine) as session:
            yield session

    converter = UnificationSQLConversionApplication(artifact_store=transport.store, session_factory=sessions)
    with pytest.raises(KnowledgeOperationPlanConflictError) as convert:
        await converter.arun(**transport.inputs)
    assert "membership_inventory_" in convert.value.kwargs["reason"]
    assert not [sql for sql, _ in complete.queries if sql.lstrip().upper().startswith(("UPDATE", "INSERT", "DELETE"))]
