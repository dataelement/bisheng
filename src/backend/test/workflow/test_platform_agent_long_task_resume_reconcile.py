import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from bisheng.common.errcode.flow import PlatformAgentExecutionError
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.core.context.tenant import get_current_tenant_id, tenant_execution_scope
from bisheng.worker.workflow.platform_agent_long_task import register_long_task_reconcile
from bisheng.workflow.domain.schemas.platform_agent import AgentDispatch, AgentReference, AgentRunObservation
from test.workflow.platform_agent_interaction_worker import FileLedger
from test.workflow.test_platform_agent_interaction_wait import prepare, run_worker
from test.workflow.test_platform_agent_long_task_resume_wait import CALL, resume_graph
from test.workflow.test_platform_agent_long_task_resume_wait import interaction_runtime as interaction_runtime
from test.workflow.test_platform_agent_long_task_resume_wait import long_remote as long_remote


class WorkerLost(BaseException):
    pass


@pytest.fixture
def runtime(interaction_runtime, monkeypatch, tmp_path):
    run = interaction_runtime
    monkeypatch.setattr(run.service, "enable_long_task_resume", True)
    run.provider = run.service.provider
    run.provider.ledger = FileLedger(tmp_path / "remote.sqlite3")
    return run


async def start(run, monkeypatch, *, failure=None):
    original = run.provider.start

    async def send(*args):
        observation = await original(*args)
        if failure is not None:
            raise failure()
        return observation

    monkeypatch.setattr(run.provider, "start", AsyncMock(side_effect=send))
    with tenant_execution_scope(7):
        row, dispatch = await prepare(run, resume_graph())
    if failure is WorkerLost:
        with pytest.raises(WorkerLost):
            await asyncio.to_thread(run_worker, row, dispatch)
    else:
        await asyncio.to_thread(run_worker, row, dispatch)
    return row["execution_id"], dispatch


def read(run, execution_id):
    row = run.repo.get_execution(execution_id)
    call = row["calls"][CALL]
    return row, call, call["long_task"]["resume"]


@pytest.mark.parametrize("failure", [TimeoutError, WorkerLost])
async def test_scan_recovers_original_start_without_replaying(runtime, monkeypatch, failure):
    execution_id, initial = await start(runtime, monkeypatch, failure=failure)
    provider = runtime.provider
    monkeypatch.setattr(provider, "lookup_start", AsyncMock(wraps=provider.lookup_start))
    with tenant_execution_scope(7):
        row, call, _ = read(runtime, execution_id)
        assert call["deadline"] == 1030 and not call.get("agent_run_id")
        if failure is WorkerLost:
            assert row["state"] == "RUNNING"
            assert runtime.repo.due_long_calls(7, resume_recovery=True)[0] == []
            runtime.now[0] = call["long_task"]["start_deadline"]
            original_owner = row["dispatches"][initial]["owner"]
        assert runtime.repo.due_long_calls(7, resume_recovery=True)[0] == [(execution_id, CALL)]
        await runtime.service.reconcile_long(7, execution_id, CALL)
        if failure is WorkerLost:
            stale = AgentDispatch(execution_id, initial, original_owner)
            with pytest.raises(PlatformAgentExecutionError):
                runtime.repo.close_long(stale, CALL, "FAILED", "RUN_FAILED")
        row, call, resume = read(runtime, execution_id)
    assert row["state"] == "WAITING" and row["dispatches"][initial]["state"] == "DONE"
    assert call["agent_run_id"] and call["deadline"] == 1030 and resume["phase"] == "POLL_WAIT"
    assert provider.start.await_count == provider.lookup_start.await_count == 1
    assert provider.lookup_start.await_args.args[-1] == f"{execution_id}:{CALL}"
    assert not runtime.outputs


async def test_scan_redelivers_same_dispatch_after_wakeup_and_publish_are_lost(runtime, monkeypatch):
    execution_id, _ = await start(runtime, monkeypatch)
    monkeypatch.setattr(runtime.provider, "get_status", AsyncMock(wraps=runtime.provider.get_status))
    monkeypatch.setattr(runtime.provider, "get_result", AsyncMock(wraps=runtime.provider.get_result))
    broker = SimpleNamespace(apply_async=Mock(side_effect=[ConnectionError(), None]))
    app = SimpleNamespace(task=lambda **_options: lambda func: func)
    reconcile, _ = register_long_task_reconcile(app, lambda: runtime.service, long_resume_task=broker)

    def tick(tenant_id=7):
        assert get_current_tenant_id() != 7
        monkeypatch.setattr(reconcile, "request", SimpleNamespace(headers={"tenant_id": tenant_id}), raising=False)
        reconcile()

    runtime.now[0] = 1003
    await asyncio.to_thread(tick, 8)
    runtime.provider.get_status.assert_not_awaited()
    await asyncio.to_thread(tick)
    with tenant_execution_scope(7):
        _, call, resume = read(runtime, execution_id)
    assert call["long_task"]["remote_state"] == "SUCCEEDED" and resume["phase"] == "POLL_WAIT"
    assert broker.apply_async.call_count == 0
    assert runtime.provider.get_status.await_count == 1
    runtime.now[0] += 1
    await asyncio.to_thread(tick)
    with tenant_execution_scope(7):
        row, call, resume = read(runtime, execution_id)
    dispatch = resume["dispatch_id"]
    assert resume["phase"] == "RESUME_READY" and resume["result"]["answer"]
    assert row["dispatches"][dispatch]["kind"] == "LONG_TASK_RESUME"
    assert row["dispatches"][dispatch]["state"] == "ACCEPTED" and row["state"] == "WAITING"
    status_calls = runtime.provider.get_status.await_count
    await asyncio.to_thread(tick)
    assert broker.apply_async.call_count == 1
    runtime.now[0] += 1
    await asyncio.to_thread(tick)
    assert broker.apply_async.call_count == 2
    assert broker.apply_async.call_args_list[0] == broker.apply_async.call_args_list[1]
    assert broker.apply_async.call_args.kwargs == {"args": [execution_id, CALL, dispatch], "headers": {"tenant_id": 7}}
    assert runtime.provider.get_status.await_count == status_calls
    assert runtime.provider.get_result.await_count == runtime.provider.start.await_count == 1
    assert call["deadline"] == 1030 and not runtime.outputs


async def test_poll_lease_and_remote_state_fence_late_responses(runtime, monkeypatch):
    execution_id, _ = await start(runtime, monkeypatch)
    with tenant_execution_scope(7):
        _, call, _ = read(runtime, execution_id)
        ref = AgentReference.model_validate(call["ref"])
        observation = AgentRunObservation(run_id=call["agent_run_id"], ref=ref, status="QUEUED", progress=0)
        first, until = runtime.repo.claim_long_task_resume_poll(execution_id, CALL, 7)
        assert runtime.repo.claim_long_task_resume_poll(execution_id, CALL, 7) is None
        runtime.now[0] = until
        second, _ = runtime.repo.claim_long_task_resume_poll(execution_id, CALL, 7)
        assert second != first
        assert not runtime.repo.finish_long_task_resume_poll(
            execution_id, CALL, first, observation=observation.model_copy(update={"status": "FAILED"})
        )
        assert runtime.repo.finish_long_task_resume_poll(execution_id, CALL, second, observation=observation)
        row, saved, _ = read(runtime, execution_id)
        assert row["state"] == "WAITING" and saved["long_task"]["remote_state"] == "RUNNING"


@pytest.mark.parametrize(
    "case", ["wrong_run", "wrong_version", "input", "remote_failed", "bad_output", "missing", "revoked"]
)
async def test_poll_rejects_invalid_results_and_handles_unavailable_or_terminal_runs(runtime, monkeypatch, case):
    execution_id, _ = await start(runtime, monkeypatch)
    provider = runtime.provider
    status = provider.get_status
    result = provider.get_result

    async def observe(*args):
        observation = await status(*args)
        overrides = {
            "wrong_run": {"run_id": "other-run"},
            "wrong_version": {"ref": observation.ref.model_copy(update={"version_id": "wrong"})},
            "input": {"status": "WAITING_INPUT"},
            "remote_failed": {"status": "FAILED"},
        }
        return observation.model_copy(update=overrides.get(case, {}))

    async def read_result(*args):
        observation = await result(*args)
        return observation.model_copy(update={"output": []}) if case == "bad_output" else None

    monkeypatch.setattr(provider, "get_status", AsyncMock(side_effect=observe))
    monkeypatch.setattr(provider, "get_result", AsyncMock(side_effect=read_result))
    if case == "revoked":
        monkeypatch.setattr(runtime.service, "_long_actor", AsyncMock(side_effect=UnAuthorizedError))
    runtime.now[0] = 1003
    with tenant_execution_scope(7):
        await runtime.service.reconcile_long(7, execution_id, CALL)
        if case in {"bad_output", "missing"}:
            runtime.now[0] += 1
            await runtime.service.reconcile_long(7, execution_id, CALL)
        if case == "missing":
            assert read(runtime, execution_id)[0]["state"] == "WAITING"
            runtime.now[0] = 1030
            await runtime.service.reconcile_long(7, execution_id, CALL)
        row, call, resume = read(runtime, execution_id)
    assert row["state"] == "FAILED" and resume["phase"] == "TERMINAL"
    assert "result" not in resume and not runtime.outputs
    assert all(item["kind"] != "LONG_TASK_RESUME" for item in row["dispatches"].values())
    assert (
        call["long_task"]["reason"]
        == {
            "wrong_run": "INVALID_OUTPUT",
            "wrong_version": "INVALID_OUTPUT",
            "input": "UNSUPPORTED_INPUT",
            "remote_failed": "REMOTE_FAILED",
            "bad_output": "INVALID_OUTPUT",
            "missing": "RESULT_UNAVAILABLE",
            "revoked": "FORBIDDEN",
        }[case]
    )
    if case == "revoked":
        provider.get_status.assert_not_awaited()
