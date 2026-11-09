"""§126 actual resource progress stops, with no SQL held across the guard/IO."""

from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.common.errcode.permission import PermissionPublishNotReadyError
from bisheng.permission.application.identity import PermissionActor
from test.knowledge_unification import test_move_projection as runtime
from test.knowledge_unification import test_move_projection_repository as native

database = runtime.database


async def test_actual_progress_runs_outside_sql_before_resource_io_and_skips_finalized_replay(database, monkeypatch):
    items = (native.expectation(1), native.expectation(2))
    built = await runtime.compose(database, monkeypatch, items)
    await runtime.before_modes(database, items)
    seen = []

    async def progress(item):
        assert not any(session.in_transaction() for session in built.bridge._seen)
        seen.append(item.resource_id)

    assert (
        await built.bridge.aexecute_or_resume(
            job_id=native.JOB, changes=items, actor=PermissionActor(user_id=7, tenant_id=101), progress=progress
        )
    ).complete
    assert seen == ["1", "2"]
    stop = AsyncMock(side_effect=AssertionError("completed operation has no IO"))
    assert (
        await built.bridge.aexecute_or_resume(
            job_id=native.JOB, changes=items, actor=PermissionActor(user_id=7, tenant_id=101), progress=stop
        )
    ).complete
    stop.assert_not_awaited()


@pytest.mark.parametrize("invalid", ["not_callable", "sync", "result"])
async def test_progress_contract_rejects_invalid_ports_before_fga(database, monkeypatch, invalid):
    item = native.expectation()
    built = await runtime.compose(database, monkeypatch, (item,))
    await runtime.before_modes(database, (item,))
    progress = (
        False
        if invalid == "not_callable"
        else (lambda item: None)
        if invalid == "sync"
        else AsyncMock(return_value=False)
    )
    with pytest.raises(PermissionPublishNotReadyError):
        await built.bridge.aexecute_or_resume(
            job_id=native.JOB, changes=(item,), actor=PermissionActor(user_id=7, tenant_id=101), progress=progress
        )
    assert not built.transport.calls


async def test_progress_failure_preserves_completed_original_operation_and_stops_next_io(database, monkeypatch):
    items = (native.expectation(1), native.expectation(2))
    built = await runtime.compose(database, monkeypatch, items)
    await runtime.before_modes(database, items)

    async def progress(item):
        if item.resource_id == "2":
            raise KnowledgeOperationPlanConflictError(reason="original_move_lease_lost")

    with pytest.raises(KnowledgeOperationPlanConflictError):
        await built.bridge.aexecute_or_resume(
            job_id=native.JOB, changes=items, actor=PermissionActor(user_id=7, tenant_id=101), progress=progress
        )
    async with database.sessions() as session:
        rows = (await session.execute(sa.select(native.Operation.scope_key, native.Operation.status))).all()
        assert rows == [("knowledge_file:1", "FINALIZED")]
