from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.workflow.domain.schemas.platform_agent import AgentReference
from test.workflow.test_platform_agent_long_task_contract import long_remote as long_remote
from test.workflow.test_platform_agent_long_task_run import long_run as long_run


@pytest.mark.parametrize("trigger", ["stop", "timeout"])
async def test_reconcile_uses_original_run_after_worker_owner_is_gone(long_run, trigger):
    run = long_run
    execution_id = run.dispatch.execution_id
    key = f"{run.node['id']}:0"
    ref = {"agent_id": "mock:echo", "version_id": "v1"}
    run.repo.reserve_long_call(run.dispatch, key, "fixture-digest", ref, 1000, 1002, 1003)
    run.repo.permit_long_start(run.dispatch, key)
    actor = await run.service._long_actor(run.user, run.repo.get_execution(execution_id))
    observation = await run.provider.start(actor, AgentReference(**ref), {"query": "hello"}, f"{execution_id}:{key}")
    if trigger == "stop":
        run.repo.request_stop(execution_id, cancel_long=True)
        run.repo.request_stop(execution_id, cancel_long=True)
    else:
        run.now[0] = 1003
    await run.service.reconcile_long(7, execution_id, key)
    task = run.repo.long_snapshot(execution_id, key)
    assert task["run_id"] == observation.run_id
    assert task["local_state"] == ("STOPPED" if trigger == "stop" else "TIMED_OUT")
    if trigger == "stop":
        assert task["cancel_state"] == "ACCEPTED"
        run.now[0] += 1
        await run.service.reconcile_long(7, execution_id, key)
        assert run.repo.long_snapshot(execution_id, key)["cancel_state"] == "CONFIRMED"
    else:
        assert task["remote_state"] == "SUCCEEDED" and task["cancel_state"] == "NO_ACTION"


async def test_revocation_before_reconcile_keeps_cancel_unconfirmed_without_provider_call(long_run, monkeypatch):
    run = long_run
    execution_id = run.dispatch.execution_id
    key = f"{run.node['id']}:0"
    ref = AgentReference(agent_id="mock:echo", version_id="v1")
    run.repo.reserve_long_call(run.dispatch, key, "digest", ref.model_dump(), 1000, 1005, 1030)
    run.repo.permit_long_start(run.dispatch, key)
    run.repo.request_stop(execution_id, cancel_long=True)
    monkeypatch.setattr(run.service, "_long_actor", AsyncMock(side_effect=UnAuthorizedError))
    monkeypatch.setattr(run.provider, "lookup_start", AsyncMock())
    await run.service.reconcile_long(7, execution_id, key)
    run.provider.lookup_start.assert_not_awaited()
    assert run.repo.long_snapshot(execution_id, key)["cancel_state"] == "UNCONFIRMED"


@pytest.mark.parametrize("reply", ["lost", "rejected", "no-confirmation"])
async def test_cancel_receipts_are_not_remote_termination(long_run, monkeypatch, reply):
    run = long_run
    execution_id = run.dispatch.execution_id
    key = f"{run.node['id']}:0"
    ref = AgentReference(agent_id="mock:echo", version_id="v1")
    run.repo.reserve_long_call(run.dispatch, key, "digest", ref.model_dump(), 1000, 1005, 1030)
    run.repo.permit_long_start(run.dispatch, key)
    actor = await run.service._long_actor(run.user, run.repo.get_execution(execution_id))
    await run.provider.start(actor, ref, {"query": "hello"}, f"{execution_id}:{key}")
    original = run.provider.cancel

    async def cancel(*args):
        if reply == "lost":
            await original(*args)
            raise TimeoutError
        return "REJECTED" if reply == "rejected" else "ACCEPTED"

    monkeypatch.setattr(run.provider, "cancel", AsyncMock(side_effect=cancel))
    run.repo.request_stop(execution_id, cancel_long=True)
    await run.service.reconcile_long(7, execution_id, key)
    first = run.repo.long_snapshot(execution_id, key)
    assert first["remote_state"] == "RUNNING"
    assert first["cancel_state"] == {"lost": "SENT", "rejected": "REJECTED", "no-confirmation": "ACCEPTED"}[reply]
    run.now[0] += 16 if reply == "no-confirmation" else 1
    await run.service.reconcile_long(7, execution_id, key)
    final = run.repo.long_snapshot(execution_id, key)
    assert final["local_state"] == "STOPPED"
    assert (
        final["cancel_state"] == {"lost": "CONFIRMED", "rejected": "REJECTED", "no-confirmation": "UNCONFIRMED"}[reply]
    )
    assert run.provider.cancel.await_count == 1


def test_stop_before_dispatch_permit_has_no_remote_cancel_intent(long_run):
    from bisheng.common.errcode.flow import PlatformAgentExecutionError

    run = long_run
    key = f"{run.node['id']}:0"
    run.repo.reserve_long_call(
        run.dispatch, key, "digest", {"agent_id": "mock:echo", "version_id": "v1"}, 1000, 1005, 1030
    )
    run.repo.request_stop(run.dispatch.execution_id, cancel_long=True)
    with pytest.raises(PlatformAgentExecutionError):
        run.repo.permit_long_start(run.dispatch, key)
    task = run.repo.long_snapshot(run.dispatch.execution_id, key)
    assert (task["remote_state"], task["cancel_state"]) == ("NOT_SENT", "NO_ACTION")
